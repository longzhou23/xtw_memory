"""Durable, causal Router delivery into the real Episode lifecycle.

The routing journal is the successful history. Raw receipts survive failures;
an explicit resume reuses a persisted choice after a writer failure.
"""
import copy
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime

from xtw_router.protocol import from_record, to_record
from xtw_router.retrieval import candidates_for
from .contracts import Invalid, integer, text
from .episode_runtime import normalize_event
from .store import digest, encode


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed
    except (ValueError, TypeError, AttributeError) as error:
        raise Invalid('时间必须是含时区的ISO时间') from error


def observable(event):
    return dict(message_id=event['id'], participant_id=event['speaker'],
                timestamp=event['time'], text=event['text'],
                reply_to_message_id=event['replyTo'], sequence_index=event['sequence'])


class RouterRuntime:
    def __init__(self, store, scorer, writer, *, capacity=6, eviction_batch=3,
                 ttl_seconds=900, max_span_seconds=3600, max_episode_events=80):
        for name, value, low, high in [
            ('capacity', capacity, 1, 80), ('eviction_batch', eviction_batch, 1, capacity),
            ('ttl_seconds', ttl_seconds, 1, 86400),
            ('max_span_seconds', max_span_seconds, 1, 604800),
            ('max_episode_events', max_episode_events, 1, 500)]:
            integer(value, name, low, high)
        self.store, self.scorer, self.writer = store, scorer, writer
        self.settings = dict(capacity=capacity, eviction_batch=eviction_batch,
                             ttl_seconds=ttl_seconds, max_span_seconds=max_span_seconds,
                             max_episode_events=max_episode_events)
        self.db = store.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS routing_scopes(scope TEXT PRIMARY KEY, settings TEXT NOT NULL,
          clock TEXT, busy_pid INTEGER, busy_token TEXT);
        CREATE TABLE IF NOT EXISTS routing_events(scope TEXT NOT NULL, event_id TEXT NOT NULL,
          sequence_index INTEGER NOT NULL, time TEXT NOT NULL, event TEXT NOT NULL,
          status TEXT NOT NULL, episode TEXT, payload TEXT, prediction TEXT, result TEXT, error TEXT,
          PRIMARY KEY(scope,event_id), UNIQUE(scope,sequence_index));
        CREATE INDEX IF NOT EXISTS routing_pending ON routing_events(scope,status,sequence_index);
        ''')
        self.db.commit()

    @contextmanager
    def _lease(self, scope, recovery=False):
        text(scope, 'scope', 200)
        token = uuid.uuid4().hex
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT * FROM routing_scopes WHERE scope=?', (scope,)).fetchone()
            if row:
                if row['settings'] != encode(self.settings):
                    raise Invalid('重启Router设置与冻结设置不一致')
                if row['busy_pid'] is not None:
                    try:
                        os.kill(row['busy_pid'], 0)
                        alive = True
                    except ProcessLookupError:
                        alive = False
                    except PermissionError:
                        alive = True
                    if alive or not recovery:
                        raise Invalid('同scope有在途操作；死进程须显式恢复')
            else:
                self.db.execute('INSERT INTO routing_scopes(scope,settings) VALUES(?,?)',
                                (scope, encode(self.settings)))
            self.db.execute('UPDATE routing_scopes SET busy_pid=?,busy_token=? WHERE scope=?',
                            (os.getpid(), token, scope))
        try:
            yield
        finally:
            with self.db:
                self.db.execute('UPDATE routing_scopes SET busy_pid=NULL,busy_token=NULL WHERE scope=? AND busy_token=?',
                                (scope, token))

    def _pending(self, scope):
        return self.db.execute("SELECT * FROM routing_events WHERE scope=? AND status!='COMMITTED' ORDER BY sequence_index LIMIT 1", (scope,)).fetchone()

    def _row(self, scope, event_id):
        return self.db.execute('SELECT * FROM routing_events WHERE scope=? AND event_id=?', (scope, event_id)).fetchone()

    def _normalize(self, scope, event):
        if not isinstance(event, dict) or 'sequence' not in event:
            raise Invalid('Router事件必须声明sequence')
        integer(event['sequence'], 'sequence', 0, 1000000000)
        body = normalize_event(self.store, scope, '', {k: v for k, v in event.items() if k != 'sequence'})
        # The CPU protocol has a smaller explicit input contract than the writer.
        if len(body['text']) > 4096:
            raise Invalid('Router文本超过4096字符；不隐式截断')
        return {**body, 'sequence': event['sequence']}

    def _check_time(self, scope, time):
        row = self.db.execute('SELECT clock FROM routing_scopes WHERE scope=?', (scope,)).fetchone()
        if row and row['clock'] and instant(time) < instant(row['clock']):
            raise Invalid('同scope时间不能倒退')

    def ingest(self, scope, event):
        with self._lease(scope):
            event = self._normalize(scope, event)
            prior = self._row(scope, event['id'])
            if prior:
                if prior['event'] != encode(event):
                    raise Invalid('重复事件id内容不同')
                if prior['status'] != 'COMMITTED':
                    raise Invalid('该事件未送达完成，须显式恢复')
                return {**json.loads(prior['result']), 'duplicate': True}
            if self._pending(scope):
                raise Invalid('同scope存在未完成事件，须显式恢复')
            self._check_time(scope, event['time'])
            last = self.db.execute('SELECT MAX(sequence_index) FROM routing_events WHERE scope=?', (scope,)).fetchone()[0]
            if last is not None and event['sequence'] <= last:
                raise Invalid('同scope sequence必须严格递增')
            with self.db:
                self.db.execute('INSERT INTO routing_events(scope,event_id,sequence_index,time,event,status) VALUES(?,?,?,?,?,?)',
                                (scope, event['id'], event['sequence'], event['time'], encode(event), 'RECEIVED'))
            return self._deliver(scope, event['id'])

    def resume(self, scope, event_id):
        with self._lease(scope, recovery=True):
            row = self._row(scope, event_id)
            if row is None:
                raise Invalid('没有可恢复的原始接收')
            if row['status'] == 'COMMITTED':
                return {**json.loads(row['result']), 'duplicate': True}
            if self._pending(scope)['event_id'] != event_id:
                raise Invalid('须按原接收顺序恢复')
            # A process may die while its external writer is still in flight.
            # An explicit resume is not authority to issue a duplicate model call.
            if self.db.execute("SELECT 1 FROM writes WHERE scope=? AND status='PENDING'", (scope,)).fetchone():
                raise Invalid('存在PENDING模型写入，须先人工确认在途调用结果')
            return self._deliver(scope, event_id)

    def _history(self, scope):
        history, episodes = [], {}
        rows = self.db.execute("SELECT * FROM routing_events WHERE scope=? AND status='COMMITTED' ORDER BY sequence_index", (scope,)).fetchall()
        for row in rows:
            event = json.loads(row['event'])
            actual = self.db.execute('SELECT * FROM events WHERE scope=? AND id=?', (scope, row['event_id'])).fetchone()
            if actual is None or actual['episode'] != row['episode'] or any(
                actual[column] != event[key] for column, key in [
                    ('speaker','speaker'), ('time','time'), ('text','text'), ('reply_to','replyTo'),
                    ('display_name','displayName'), ('role','role'), ('media','media')]):
                raise Invalid('成功路由的原始来源或归属发生变化')
            message = observable(event)
            history.append(message)
            if self.store._episode(scope, row['episode'])['status'] == 'OPEN':
                episodes.setdefault(row['episode'], []).append(message)
        return history, episodes

    def _input(self, scope, event):
        history, episodes = self._history(scope)
        target = observable(event)
        payload = from_record({'packet': {'case_id': event['id'], 'conversation_id': scope,
                                         'target': target, 'prior_context': history[-8:]},
                               'mapped': {'candidates': candidates_for(episodes, target)}})
        to_record(payload)
        return payload

    def _finish(self, scope, now=None, all_episodes=False):
        completed = []
        owned = self.db.execute("SELECT DISTINCT episode FROM routing_events WHERE scope=? AND episode IS NOT NULL ORDER BY sequence_index", (scope,)).fetchall()
        for row in owned:
            episode = row[0]
            raw = self.db.execute('SELECT time FROM events WHERE scope=? AND episode=? ORDER BY seq', (scope, episode)).fetchall()
            if not raw:
                continue
            ep = self.store._episode(scope, episode)
            due = all_episodes or len(raw) >= self.settings['max_episode_events']
            if now is not None:
                due = due or (instant(now)-instant(raw[-1][0])).total_seconds() >= self.settings['ttl_seconds']
                due = due or (instant(now)-instant(raw[0][0])).total_seconds() >= self.settings['max_span_seconds']
            if ep['status'] == 'OPEN' and due:
                self.store.close_episode(scope, episode)
                ep = self.store._episode(scope, episode)
            if ep['status'] == 'CLOSED':
                if self.db.execute("SELECT 1 FROM consolidations WHERE scope=? AND episode=? AND status='PENDING'", (scope, episode)).fetchone():
                    raise Invalid('Final有PENDING模型调用，不能隐式重复')
                completed.append(self.store.consolidate(scope, episode, model=self.writer))
        return completed

    def _deliver(self, scope, event_id):
        row = self._row(scope, event_id)
        event = json.loads(row['event'])
        try:
            if row['prediction'] is None:
                self._history(scope)
                self._finish(scope, event['time'])
                payload = self._input(scope, event)
                with self.db:
                    self.db.execute('UPDATE routing_events SET payload=?,error=NULL WHERE scope=? AND event_id=?',
                                    (encode(payload), scope, event_id))
                prediction = self.scorer.route(copy.deepcopy(payload)) if payload['candidates'] else {'decision':'NEW','episode_id':None,'reason':'NO_OPEN_CANDIDATE'}
                if self._input(scope, event) != payload:
                    raise Invalid('分类期间实际历史或候选变化，拒绝过期选择')
                if not isinstance(prediction, dict) or prediction.get('decision') not in ('NEW','CONTINUE'):
                    raise Invalid('Router结果必须是NEW或CONTINUE')
                episode = prediction.get('episode_id')
                if prediction['decision'] == 'NEW':
                    if episode is not None:
                        raise Invalid('NEW不能指定已有候选')
                    episode = 'route-' + digest([scope, event_id])[:24]
                elif episode not in {c['episode_id'] for c in payload['candidates']}:
                    raise Invalid('Router选择不在实际候选集合')
                with self.db:
                    self.db.execute("UPDATE routing_events SET status='ROUTED',prediction=?,episode=? WHERE scope=? AND event_id=?",
                                    (encode(prediction), episode, scope, event_id))
            else:
                prediction, episode = json.loads(row['prediction']), row['episode']
                if self._input(scope, event) != json.loads(row['payload']):
                    raise Invalid('恢复时已冻结候选或来源变化，不能沿用过期选择')
            self.store.create_episode(scope, episode, episode, lifecycle='episode',
                                      capacity=self.settings['capacity'], eviction_batch=self.settings['eviction_batch'])
            receipt = self.store.advance_episode(scope, episode,
                                                {k:v for k,v in event.items() if k != 'sequence'}, model=self.writer)
            result = dict(decision=prediction['decision'], assigned_episode_id=episode,
                          prediction=prediction, delivery=receipt, duplicate=False)
            with self.db:
                self.db.execute("UPDATE routing_events SET status='COMMITTED',result=?,error=NULL WHERE scope=? AND event_id=?",
                                (encode(result), scope, event_id))
                self.db.execute('UPDATE routing_scopes SET clock=? WHERE scope=?', (event['time'], scope))
            return result
        except BaseException as error:
            with self.db:
                self.db.execute("UPDATE routing_events SET status=CASE WHEN prediction IS NULL THEN 'FAILED' ELSE 'ROUTED' END,error=? WHERE scope=? AND event_id=?",
                                (str(error), scope, event_id))
            raise

    def tick(self, scope, time):
        instant(time)
        with self._lease(scope):
            if self._pending(scope):
                raise Invalid('存在未完成事件，须先恢复')
            self._check_time(scope, time)
            self._history(scope)
            result = self._finish(scope, time)
            with self.db:
                self.db.execute('UPDATE routing_scopes SET clock=? WHERE scope=?', (time, scope))
            return result

    def close_all(self, scope):
        with self._lease(scope):
            if self._pending(scope):
                raise Invalid('存在未完成事件，须先恢复')
            self._history(scope)
            return self._finish(scope, all_episodes=True)
