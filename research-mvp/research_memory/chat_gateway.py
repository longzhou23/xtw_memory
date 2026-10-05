"""Loopback ingress with a durable inbox and one serial lifecycle worker."""
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import threading
from urllib.parse import parse_qs, urlsplit

from .contracts import Invalid, integer, text
from .episode_runtime import normalize_event
from .routing import RouterRuntime, instant
from .store import Store, encode

PROFILE = dict(capacity=12, eviction_batch=6, ttl_seconds=900,
               max_span_seconds=3600, max_episode_events=24)


class InboxFull(Invalid):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def alive(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Inbox:
    def __init__(self, path, *, max_pending=1000, max_rows=50000,
                 max_bytes=268435456, text_limit=1024, profile=None, identity=None):
        self.path = str(Path(path).resolve())
        for key, value, high in [('max_pending', max_pending, 100000),
                                 ('max_rows', max_rows, 1000000),
                                 ('max_bytes', max_bytes, 10**10),
                                 ('text_limit', text_limit, 4096)]:
            integer(value, key, 1, high)
        self.config = dict(version=1, max_pending=max_pending, max_rows=max_rows,
                           max_bytes=max_bytes, text_limit=text_limit,
                           profile=dict(PROFILE if profile is None else profile), identity=identity)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # Fail before touching a populated research database. No migrations.
        with closing(sqlite3.connect(self.path)) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and 'chat_config' not in tables:
                raise Invalid('消息网关必须使用专用新库，不迁移研究库')
            if tables:
                row = db.execute('SELECT value FROM chat_config WHERE id=1').fetchone()
                if row is None or row[0] != encode(self.config):
                    raise Invalid('消息网关冻结配置不同，使用新库')
        Path(self.path).chmod(0o600)
        with closing(Store(self.path)) as store:
            RouterRuntime(store, None, None, **self.config['profile'])
            store.db.executescript('''
            CREATE TABLE IF NOT EXISTS chat_config(id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,
              scope TEXT NOT NULL, kind TEXT NOT NULL, external_id TEXT NOT NULL,
              payload TEXT NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL,
              received TEXT NOT NULL, updated TEXT NOT NULL, result TEXT, error TEXT,
              UNIQUE(scope,kind,external_id));
            CREATE INDEX IF NOT EXISTS chat_pending ON chat_jobs(status,scope,id);
            CREATE TABLE IF NOT EXISTS chat_worker(id INTEGER PRIMARY KEY,
              pid INTEGER, state TEXT NOT NULL, updated TEXT NOT NULL, error TEXT, metrics TEXT);
            CREATE TABLE IF NOT EXISTS chat_reviews(job_id INTEGER NOT NULL,
              confirmed TEXT NOT NULL, writes TEXT NOT NULL, PRIMARY KEY(job_id,confirmed));
            ''')
            store.db.execute('INSERT OR IGNORE INTO chat_config VALUES(1,?)', (encode(self.config),))
            store.db.commit()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def receipt(row, duplicate=False):
        result = dict(jobId=row['id'], scope=row['scope'], kind=row['kind'],
                      id=row['external_id'], status=row['status'], received=row['received'],
                      updated=row['updated'], error=row['error'], duplicate=duplicate,
                      result=json.loads(row['result']) if row['result'] else None)
        result['event' if row['kind'] == 'message' else 'operation'] = json.loads(row['payload'])
        return result

    def _enqueue(self, scope, kind, external_id, payload, archived=None):
        text(scope, 'scope', 200); text(external_id, 'id', 200)
        body, stamp = encode(payload), now()
        size = len(encode([scope, kind, external_id, payload]).encode())
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM chat_jobs WHERE scope=? AND kind=? AND external_id=?',
                               (scope, kind, external_id)).fetchone()
            if prior:
                if prior['payload'] != body:
                    raise Invalid('重复id内容不同')
                return self.receipt(prior, True)
            row = db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM chat_jobs WHERE (kind='message')=?", (int(kind=='message'),)).fetchone()
            pending = db.execute("SELECT COUNT(*) FROM chat_jobs WHERE status NOT IN ('DONE','ARCHIVED')").fetchone()[0]
            if (row[0] >= self.config['max_rows'] or (kind=='message' and row[1]+size > self.config['max_bytes'])
                    or (not archived and pending >= self.config['max_pending'])):
                raise InboxFull('接收容量已满，未确认接收；稍后重送或换新库')
            cursor = db.execute('INSERT INTO chat_jobs(scope,kind,external_id,payload,size,status,received,updated,result) VALUES(?,?,?,?,?,?,?,?,?)',
                                (scope, kind, external_id, body, size,
                                 'ARCHIVED' if archived else 'QUEUED', stamp, stamp,
                                 encode({'reason':archived}) if archived else None))
            return self.receipt(db.execute('SELECT * FROM chat_jobs WHERE id=?', (cursor.lastrowid,)).fetchone())

    def message(self, scope, event):
        text(scope, 'scope', 200)
        empty_media = isinstance(event, dict) and event.get('text') == '' and event.get('media') == 'unreadable'
        with closing(Store(self.path)) as store:
            normalized = normalize_event(store, scope, '', {**event, 'text':'[不可读取媒体]'} if empty_media else event)
        if empty_media:
            normalized['text'] = ''
        archived = 'UNREADABLE_ONLY' if empty_media else (
            'TEXT_LIMIT' if len(normalized['text']) > self.config['text_limit'] else None)
        return self._enqueue(scope, 'message', normalized['id'], normalized, archived)

    def close_scope(self, scope, request_id):
        return self._enqueue(scope, 'close', request_id, {})

    def get(self, job_id):
        integer(job_id, 'jobId', 1, 10**12)
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM chat_jobs WHERE id=?', (job_id,)).fetchone()
            if row is None:
                raise Invalid('任务不存在')
            return self.receipt(row)

    def list(self, scope, after=0, limit=200):
        text(scope, 'scope', 200); integer(after, 'after', 0, 10**12); integer(limit, 'limit', 1, 200)
        with closing(self.connect()) as db:
            return [self.receipt(r) for r in db.execute('SELECT * FROM chat_jobs WHERE scope=? AND id>? ORDER BY id LIMIT ?', (scope, after, limit))]

    def retry(self, job_id):
        integer(job_id, 'jobId', 1, 10**12)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM chat_jobs WHERE id=?', (job_id,)).fetchone()
            if row is None or row['status'] != 'FAILED':
                raise Invalid('仅已知FAILED可重试；REVIEW必须先核查在途结果')
            if db.execute("SELECT 1 FROM writes WHERE scope=? AND status='PENDING'", (row['scope'],)).fetchone():
                raise Invalid('PENDING调用必须先核查，禁止重复模型调用')
            db.execute("UPDATE chat_jobs SET status='QUEUED',error=NULL,updated=? WHERE id=?", (now(), job_id))
        return self.get(job_id)

    def confirm_ended(self, job_id, confirmation):
        """Operator asserts the old process/call has ended; retain the audit."""
        integer(job_id, 'jobId', 1, 10**12)
        if confirmation is not True:
            raise Invalid('必须明确确认旧进程及外部调用已经结束')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('SELECT * FROM chat_jobs WHERE id=?', (job_id,)).fetchone()
            if job is None or job['status'] != 'REVIEW':
                raise Invalid('仅REVIEW任务需要核查确认')
            lease = db.execute('SELECT busy_pid FROM routing_scopes WHERE scope=?', (job['scope'],)).fetchone()
            if lease and alive(lease[0]):
                raise Invalid('旧scope进程仍存活，不能确认结束')
            writes = [r[0] for r in db.execute("SELECT id FROM writes WHERE scope=? AND status='PENDING'", (job['scope'],))]
            reason = '操作者已确认调用结束但无已提交结果；可显式重新执行，历史失败保留'
            for write_id in writes:
                db.execute("UPDATE writes SET status='FAILED',error=? WHERE id=?", (reason,write_id))
                db.execute("UPDATE consolidations SET status='FAILED' WHERE write_id=?", (write_id,))
            db.execute('DELETE FROM episode_busy WHERE scope=?', (job['scope'],))
            db.execute('UPDATE routing_scopes SET busy_pid=NULL,busy_token=NULL WHERE scope=?', (job['scope'],))
            db.execute('INSERT INTO chat_reviews VALUES(?,?,?)', (job_id,now(),encode(writes)))
            db.execute("UPDATE chat_jobs SET status='FAILED',error=?,updated=? WHERE id=?", (reason,now(),job_id))
        return self.get(job_id)

    def worker_state(self, state, error=None, metrics=None):
        with closing(self.connect()) as db, db:
            db.execute('INSERT OR REPLACE INTO chat_worker VALUES(1,?,?,?,?,?)',
                       (os.getpid(), state, now(), error, encode(metrics or {})))

    def health(self):
        with closing(self.connect()) as db:
            counts = {r[0]:r[1] for r in db.execute('SELECT status,COUNT(*) FROM chat_jobs GROUP BY status')}
            worker = db.execute('SELECT * FROM chat_worker WHERE id=1').fetchone()
            state = worker['state'] if worker and alive(worker['pid']) else 'STOPPED'
            return dict(status='ok' if state == 'READY' else 'degraded', worker=state,
                        queued=counts.get('QUEUED',0), running=counts.get('RUNNING',0),
                        failed=counts.get('FAILED',0), review=counts.get('REVIEW',0),
                        archived=counts.get('ARCHIVED',0), done=counts.get('DONE',0),
                        error=worker['error'] if worker else None,
                        metrics=json.loads(worker['metrics']) if worker else {})


class Worker:
    def __init__(self, inbox, scorer, writer):
        self.inbox, self.closed = inbox, False
        self.lock = open(inbox.path+'.worker.lock', 'a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.lock.close()
            raise Invalid('数据库已有工作进程') from error
        self.store = None
        try:
            inbox.worker_state('LOADING')
            self.scorer = scorer() if callable(scorer) else scorer
            self.writer = writer() if callable(writer) else writer
            identity = inbox.config['identity']
            if identity and identity.get('routerSealSha256') != getattr(self.scorer,'identity',{}).get('seal_sha256'):
                raise Invalid('常驻Router身份与冻结配置不同')
            self.store = Store(inbox.path)
            self.runtime = RouterRuntime(self.store, self.scorer, self.writer, **inbox.config['profile'])
            self._recover()
            self.inbox.worker_state('READY', metrics=self.metrics())
        except BaseException as error:
            inbox.worker_state('ERROR', str(error)); self.close(update=False)
            raise

    def metrics(self):
        return {key:getattr(self.scorer, key, None) for key in ('requests','passes','active_seconds')}

    def close(self, update=True):
        if self.closed:
            return
        self.closed = True
        if self.store:
            self.store.close()
        if update:
            self.inbox.worker_state('STOPPED')
        self.lock.close()

    def _update(self, job_id, status, result=None, error=None):
        with self.store.db:
            self.store.db.execute('UPDATE chat_jobs SET status=?,result=?,error=?,updated=? WHERE id=?',
                                  (status, encode(result) if result is not None else None, error, now(), job_id))

    def _recover(self):
        db = self.store.db
        for job in db.execute("SELECT * FROM chat_jobs WHERE status='RUNNING' ORDER BY id").fetchall():
            route = db.execute('SELECT * FROM routing_events WHERE scope=? AND event_id=?',
                               (job['scope'],job['external_id'])).fetchone() if job['kind']=='message' else None
            pending = db.execute("SELECT 1 FROM writes WHERE scope=? AND status='PENDING'", (job['scope'],)).fetchone()
            if route and route['status']=='COMMITTED':
                self._update(job['id'], 'DONE', json.loads(route['result']))
            elif pending:
                self._update(job['id'], 'REVIEW', error='进程中断且存在PENDING模型调用；核查前禁止重发')
            elif route:
                self._update(job['id'], 'FAILED', error='进程中断；原始路由已保存，可显式重试')
            else:
                lease = db.execute('SELECT busy_pid FROM routing_scopes WHERE scope=?', (job['scope'],)).fetchone()
                if lease and alive(lease['busy_pid']):
                    self._update(job['id'], 'REVIEW', error='仍有存活的scope操作，须核查')
                else:
                    with db:
                        db.execute('UPDATE routing_scopes SET busy_pid=NULL,busy_token=NULL WHERE scope=?', (job['scope'],))
                    self._update(job['id'], 'QUEUED')

    def step(self):
        db = self.store.db
        with db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute("""SELECT j.* FROM chat_jobs j WHERE j.status='QUEUED'
              AND NOT EXISTS(SELECT 1 FROM chat_jobs earlier WHERE earlier.scope=j.scope
                AND earlier.id<j.id AND earlier.status NOT IN ('DONE','ARCHIVED'))
              ORDER BY j.id LIMIT 1""").fetchone()
            if job is None:
                return False
            db.execute("UPDATE chat_jobs SET status='RUNNING',updated=? WHERE id=?", (now(),job['id']))
        try:
            if job['kind']=='message':
                event = json.loads(job['payload'])
                prior = self.runtime._row(job['scope'],event['id'])
                clock = db.execute('SELECT clock FROM routing_scopes WHERE scope=?', (job['scope'],)).fetchone()
                if not prior and clock and clock[0] and instant(event['time']) < instant(clock[0]):
                    self._update(job['id'], 'ARCHIVED', {'reason':'LATE_MESSAGE'})
                    return True
                event['sequence'] = job['id']
                result = self.runtime.resume(job['scope'],event['id']) if prior else self.runtime.ingest(job['scope'],event)
            elif job['kind']=='close':
                result = self.runtime.close_all(job['scope'])
            else:
                result = self.runtime.tick(job['scope'],json.loads(job['payload'])['time'])
            self._update(job['id'], 'DONE', result)
        except Exception as error:
            pending = db.execute("SELECT 1 FROM writes WHERE scope=? AND status='PENDING'", (job['scope'],)).fetchone()
            self._update(job['id'], 'REVIEW' if pending else 'FAILED', error=str(error))
        finally:
            self.inbox.worker_state('READY', metrics=self.metrics())
        return True

    def schedule_idle(self, time=None):
        stamp, count = time or now(), 0
        current = instant(stamp)
        db = self.store.db
        for scope, episode, first, last, length in db.execute("""SELECT g.scope,g.episode,f.time,l.time,g.length FROM (
          SELECT e.scope,e.episode,MIN(e.seq) AS first_seq,MAX(e.seq) AS last_seq,COUNT(*) AS length FROM events e
          JOIN episodes p ON p.scope=e.scope AND p.id=e.episode
          WHERE p.status='OPEN' AND EXISTS(SELECT 1 FROM routing_events r WHERE r.scope=e.scope AND r.episode=e.episode)
          GROUP BY e.scope,e.episode) g JOIN events f ON f.seq=g.first_seq JOIN events l ON l.seq=g.last_seq""").fetchall():
            due = ((current-instant(last)).total_seconds() >= self.runtime.settings['ttl_seconds']
                   or (current-instant(first)).total_seconds() >= self.runtime.settings['max_span_seconds']
                   or length >= self.runtime.settings['max_episode_events'])
            if current < instant(last) or not due or db.execute("SELECT 1 FROM chat_jobs WHERE scope=? AND status NOT IN ('DONE','ARCHIVED')", (scope,)).fetchone():
                continue
            try:
                self.inbox._enqueue(scope,'tick',f'idle-{episode}-{length}',{'time':stamp})
            except InboxFull:
                continue
            count += 1
        return count


def make_server(inbox, token, port=8767, reader=None):
    text(token, 'token', 200)
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_):
            pass
        def send(self, status, value):
            data = encode(value).encode()
            self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store')
            self.send_header('Connection','close'); self.end_headers(); self.wfile.write(data)
            self.close_connection = True
        def authorized(self):
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
                self.send(403, {'error':'Host拒绝'}); return False
            if not hmac.compare_digest(self.headers.get('Authorization',''),f'Bearer {token}'):
                self.send(401, {'error':'需要本地令牌'}); return False
            return True
        def do_GET(self):
            if not self.authorized():return
            target=urlsplit(self.path);query=parse_qs(target.query)
            try:
                if target.path=='/health':value=inbox.health()
                elif target.path=='/api/job':value=inbox.get(int(query['id'][0]))
                elif target.path=='/api/jobs':value=inbox.list(query['scope'][0],int(query.get('after',['0'])[0]),int(query.get('limit',['50'])[0]))
                elif target.path in ('/api/summary','/api/memories'):
                    with closing(Store(inbox.path)) as store:
                        scope=query['scope'][0];text(scope,'scope',200)
                        value=store.summary(scope) if target.path=='/api/summary' else store.page(scope,'nodes',int(query.get('after',['0'])[0]),int(query.get('limit',['50'])[0]))
                else:self.send(404,{'error':'接口不存在'});return
                self.send(200,value)
            except (Invalid,ValueError,KeyError) as error:self.send(400,{'error':str(error)})
            except sqlite3.Error:self.send(503,{'error':'存储暂不可用，请重试'})
        def do_POST(self):
            if not self.authorized():return
            try:
                if self.headers.get('Content-Type','').split(';')[0]!='application/json' or self.headers.get('Transfer-Encoding'):
                    raise Invalid('只接受定长JSON')
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 65536:raise Invalid('请求长度须为1至65536字节')
                self.connection.settimeout(5)
                value=json.loads(self.rfile.read(length))
                if not isinstance(value,dict):raise Invalid('请求必须是对象')
                if self.path=='/api/context':
                    from .context_gateway import ReadUnavailable
                    if reader is None:
                        self.send(503,{'error':'语义读取未配置'});return
                    try: result=reader.read(value)
                    except ReadUnavailable as error:
                        self.send(503,{'error':str(error)});return
                    self.send(200,result);return
                if self.path=='/api/stop' and value=={'confirm':True}:
                    self.send(202,{'stopping':True,'meaning':'停止接收，等待当前调用结束；队列保留'})
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
                    return
                if self.path=='/api/messages' and set(value)=={'scope','event'}:result=inbox.message(value['scope'],value['event'])
                elif self.path=='/api/close' and set(value)=={'scope','id'}:result=inbox.close_scope(value['scope'],value['id'])
                elif self.path=='/api/retry' and set(value)=={'jobId'}:result=inbox.retry(value['jobId'])
                elif self.path=='/api/review' and set(value)=={'jobId','confirmEnded'}:result=inbox.confirm_ended(value['jobId'],value['confirmEnded'])
                else:raise Invalid('接口或字段不合法')
                self.send(202,result)
            except (Invalid,ValueError,TypeError,UnicodeError) as error:
                status=429 if isinstance(error,InboxFull) else 409 if '内容不同' in str(error) else 400
                self.send(status,{'error':str(error)})
            except (sqlite3.Error,OSError):self.send(503,{'error':'存储或连接暂不可用，未确认接收；可重送相同id'})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    return server


def run_worker(inbox, scorer, writer, stop):
    worker=None
    failed=False
    try:
        worker=Worker(inbox,scorer,writer)
        while not stop.is_set():
            worked=worker.step()
            worker.schedule_idle()
            if not worked:stop.wait(.25)
    except Exception as error:
        failed=True
        if worker:inbox.worker_state('ERROR',str(error))
    finally:
        if worker:worker.close(update=not failed)
