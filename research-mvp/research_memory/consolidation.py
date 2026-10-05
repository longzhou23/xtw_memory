"""Auditable selective consolidation; no implicit promotion on sealing an episode."""
import uuid

from .contracts import Invalid, WRITE_SCHEMA, STRING, STRINGS, array, obj, shape, validate_write
from .providers import WRITE_PROMPT
from .store import digest, encode

SCHEMA = obj({'write': WRITE_SCHEMA, 'retainAssociations': STRINGS, 'decisions': array(obj({
    'memoryId': STRING, 'action': {'type': 'string', 'enum': ['KEEP', 'MERGE', 'ARCHIVE', 'DEFER']},
    'targets': STRINGS, 'reason': STRING}))})
PROMPT = WRITE_PROMPT + '''
本次是临时记忆到持久认知的巩固，不是追加普通检查点。events是整段已发生经历（不含未来问题），knownNodes包含暂存及显式注入的长期背景。
逐一审阅temporaryMemoryIds，decisions必须完整覆盖每一个且不重复：
KEEP：原文已自足且值得长期保留，原节点进入持久层，targets=[]。
MERGE：整合重复、补全发展过程或修订临时概括；targets填write.memories中新key，必须通过usedMemoryIds记录被整合的每条旧记忆。
ARCHIVE：无需独立长期召回的重复或失效临时内容，保留历史来源但退出召回，targets=[]。给出具体理由，不因玩笑或互动就自动归档。
DEFER：还需要后续发展，继续暂存且可以被当前话题读取，targets=[]；不能因此漏掉明确已经发生的说话行为。
write是新的持久记忆/实体/关联；没有新节点时可为空数组。MERGE不是事实纠错，只有明确同主体纠错才填supersedes；不要把普通合并伪装成纠错。
保留计划→修改→确认/取消的时间过程。说“周日见”不等于已经出行；一次偏好不概括成长期性格。持久记忆可包含有边界的不确定性。
不能依赖临时总结作为唯一事实证据，要回查原始事件。reply_to有ID而目标不在输入时，明确写“目标正文不在本次输入”，不要写成“没有回复关系”。
旧关联不自动进入长期图。已经有完整证据、端点无需更改的旧关系，审阅后将其recordIds逐一填入retainAssociations，不要重新输出相同关系和引用。只有新建/改换端点的关系才放write.associations。端点只能是KEEP节点、持久节点或新节点，不能指向DEFER/ARCHIVE/MERGE掉的旧记忆。
已注入长期背景可用于跨经历关联和明确更正，但不要只因为同主题就修改旧认识。
每个新增记忆至少使用一个temporaryMemoryIds中的记忆，并将该临时记忆的MERGE targets指向新key。
当输入是selected范围时，只处理temporaryMemoryIds指定的临时记忆。其他contextEvents供理解发展过程，不为未选话题额外造持久记忆；未选记忆仍暂存，不能隐式替代或提升。
输入knownNodes/knownAssociations的evidenceRefs是原引用的无损定位：eventId以及该事件text的Python Unicode字符半开区间[start,end)。原文在events/contextEvents，仅以原文验证内容，不把索引当事实。保留关系的原引用由程序保留；新输出仍使用逐字quote，不输出坐标。
这次输出是{write,decisions,retainAssociations}；沿用写入契约的字段与来源约束，所有events被引用或明确列入write.skipped。
'''


def model_input(bundle):
    """Lossless source spans replace repeated quotes; audit input stays uncompressed."""
    events = {e['id']: e for e in bundle['events']+bundle['contextEvents']}
    def refs(evidence):
        result = []
        for e in evidence:
            if e['eventId'] not in events:
                raise Invalid('巩固引用来源未载入，拒绝压缩缺失来源')
            body = events[e['eventId']]['text']
            start = body.find(e['quote'])
            if start < 0 or not e['quote']:
                raise Invalid('巩固引用不是原文片段')
            result.append({'eventId': e['eventId'], 'start': start, 'end': start+len(e['quote'])})
        return result
    def node(n):
        return {**{k: n[k] for k in ('id','type','kind','label','subject','status','stage','speakerId','usedMemoryIds')},
                'evidenceRefs': refs(n['evidence'])}
    def edge(e):
        return {**{k: e[k] for k in ('recordIds','source','target','relation','strength','rationale')},
                'evidenceRefs': refs(e['evidence'])}
    def event(e):
        return {k: e[k] for k in ('id','speaker','time','text','reply_to')}
    return {**{k: v for k,v in bundle.items() if k not in ('events','contextEvents','knownNodes','knownAssociations')},
            'events': [event(e) for e in bundle['events']], 'contextEvents': [event(e) for e in bundle['contextEvents']],
            'knownNodes': [node(n) for n in bundle['knownNodes']],
            'knownAssociations': [edge(e) for e in bundle['knownAssociations']]}


def prepare(store, scope, episode, memory_ids, temporary_ids=None):
    ep = store._episode(scope, episode)
    if ep['lifecycle'] != 'consolidate' or ep['status'] != 'SEALED':
        raise Invalid('先结束两层话题（SEALED），再执行巩固')
    if (not isinstance(memory_ids, (list, tuple)) or any(not isinstance(i, str) for i in memory_ids)
            or len(memory_ids) > 40 or len(set(memory_ids)) != len(memory_ids)):
        raise Invalid('持久背景最多40条且不能重复')
    events = [dict(r) for r in store.db.execute('SELECT * FROM events WHERE scope=? AND episode=? ORDER BY seq LIMIT 501', (scope, episode))]
    if any(not e['processed'] for e in events):
        raise Invalid('先整理全部待处理事件')
    nodes = {r['id']: store.node(r) for r in store.db.execute(
        "SELECT * FROM nodes WHERE scope=? AND episode=? AND stage!='ARCHIVED' ORDER BY seq LIMIT 501", (scope, episode))}
    temporary = [n['id'] for n in nodes.values() if n['type'] == 'MEMORY' and n['status'] == 'CURRENT' and n['stage'] == 'TEMPORARY']
    if len(events)>500 or len(nodes)>500:
        raise Invalid('经历超过500事件/节点预算；不能隐式截断')
    unselected = 0
    source_context = []
    if temporary_ids is not None:
        if (not isinstance(temporary_ids, (list,tuple)) or not 1<=len(temporary_ids)<=12
                or any(not isinstance(i,str) for i in temporary_ids) or len(set(temporary_ids))!=len(temporary_ids)
                or set(temporary_ids)-set(temporary)):
            raise Invalid('选择1–12条无重复的本话题CURRENT临时记忆')
        unselected = len(temporary)-len(temporary_ids)
        temporary = list(temporary_ids)
        chosen = set(temporary) | {nodes[i]['subject'] for i in temporary}
        # Keep entity bridges, but never silently select other temporary memories.
        for e in store.edges_from(scope, chosen, episode=episode, record_budget=1000):
            for ident in (e['source'],e['target']):
                if ident in nodes and nodes[ident]['type']!='MEMORY':chosen.add(ident)
        refs = {e['eventId'] for i in temporary for e in nodes[i]['evidence']}
        source_context = [e for e in events if e['id'] not in refs]
        events = [e for e in events if e['id'] in refs]
        nodes = {i:n for i,n in nodes.items() if i in chosen}
    selected = store.visible_nodes(scope, memory_ids)
    if set(selected) != set(memory_ids) or any(n['type'] != 'MEMORY' or n['status'] != 'CURRENT' for n in selected.values()):
        raise Invalid('背景必须是同scope可见的当前持久记忆')
    nodes.update(selected)
    subjects = {n['subject'] for n in nodes.values() if n.get('subject')} - set(nodes)
    nodes.update(store.visible_nodes(scope, subjects, episode))
    if subjects - set(nodes):
        raise Invalid('记忆主体不可见')
    # Keep available reply targets and source citations, without pulling entire other episodes.
    context_ids = {e['reply_to'] for e in events if e['reply_to']}
    cited_ids = {e['eventId'] for n in nodes.values() for e in n['evidence']}
    context_ids.update(cited_ids)
    context_ids -= {e['id'] for e in events+source_context}
    context = source_context[:]
    for ident in sorted(context_ids):
        row = store.db.execute('''SELECT e.* FROM events e JOIN episodes p ON p.scope=e.scope AND p.id=e.episode
          WHERE e.scope=? AND e.id=? AND (e.episode=? OR p.status IN ('CLOSED','CONSOLIDATED') OR ?)''', (scope, ident, episode, ident in cited_ids)).fetchone()
        if row:
            context.append(dict(row))
    bundle = {'scope': scope, 'episode': ep,
              'scopeRevision': store.db.execute('SELECT revision FROM scopes WHERE id=?', (scope,)).fetchone()[0],
              'events': events, 'contextEvents': context, 'knownNodes': list(nodes.values()),
              'temporaryMemoryIds': temporary,
              'selection': 'all' if temporary_ids is None else 'selected',
              'unselectedTemporaryCount': unselected,
              'knownAssociations': store.edges_from(scope, nodes, within=True, record_budget=1000, episode=episode)}
    if not temporary and not events:
        raise Invalid('没有可巩固的经历')
    if len(events) > 500 or len(nodes) > 500 or len(context) > 500 or len(encode(bundle)) > 180000:
        raise Invalid('巩固输入超过500事件/节点或180000字符预算；不静默截断')
    return bundle


def validate(output, bundle):
    # Explicit old reviewed drafts remain replayable; new model schema includes the field.
    shape({**output, 'retainAssociations': output.get('retainAssociations', [])}, SCHEMA)
    draft = output['write']
    validate_write(draft, bundle)
    decisions = {d['memoryId']: d for d in output['decisions']}
    if len(decisions) != len(output['decisions']) or set(decisions) != set(bundle['temporaryMemoryIds']):
        raise Invalid('每条当前临时记忆必须有且仅有一个巩固决定')
    memories = {n['key']: n for n in draft['memories']}
    for ident, d in decisions.items():
        if d['action'] == 'MERGE':
            if not d['targets'] or len(set(d['targets'])) != len(d['targets']):
                raise Invalid('MERGE必须指定唯一的新记忆key')
            for key in d['targets']:
                if key not in memories or ident not in memories[key]['usedMemoryIds']:
                    raise Invalid('合并目标必须存在且声明使用原临时记忆')
        elif d['targets']:
            raise Invalid('仅MERGE可以有targets')
    for n in memories.values():
        inputs = set(n['usedMemoryIds']) & set(decisions)
        if not inputs or any(decisions[i]['action'] != 'MERGE' or n['key'] not in decisions[i]['targets'] for i in inputs):
            raise Invalid('新持久记忆必须与MERGE决定双向对应')
        if any(i in decisions and (decisions[i]['action'] != 'MERGE' or n['key'] not in decisions[i]['targets']) for i in n['supersedes']):
            raise Invalid('不能替代KEEP/DEFER/ARCHIVE记忆')
    unavailable = {i for i, d in decisions.items() if d['action'] != 'KEEP'}
    known = {n['id']: n for n in bundle['knownNodes']}
    available_edges = {i: e for e in bundle['knownAssociations'] for i in e['recordIds']}
    retained = output.get('retainAssociations', [])
    if len(set(retained)) != len(retained) or any(i not in available_edges for i in retained):
        raise Invalid('保留关联只能是已注入的唯一recordId')
    for e in draft['associations'] + [available_edges[i] for i in retained]:
        for ident in (e['source'], e['target']):
            if ident in unavailable or (ident in known and known[ident]['status'] != 'CURRENT'):
                raise Invalid('持久关联不能引用已归档/合并/暂存/过期节点')
    return decisions


def consolidate(store, scope, episode, model=None, draft=None, memory_ids=(), temporary_ids=None):
    store.db.execute('BEGIN')
    try:
        bundle = prepare(store, scope, episode, memory_ids, temporary_ids)
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise
    run = 'consolidate_' + uuid.uuid4().hex
    metadata = {'provider': 'reviewed-draft' if draft is not None else getattr(model, 'name', 'missing'),
                'phase': 'CONSOLIDATION', 'inputHash': digest(bundle), 'promptHash': digest(PROMPT), 'schemaHash': digest(SCHEMA)}
    with store.db:
        store.db.execute('INSERT INTO writes VALUES(?,?,?,?,?,?,?,?)', (run, scope, episode, 'PENDING', encode(bundle), None, encode(metadata), None))
        store.db.execute('INSERT INTO consolidations VALUES(?,?,?,?,?)', (run, scope, episode, 'PENDING', None))
    try:
        if draft is None:
            if model is None:
                raise Invalid('请选择真实巩固模型或显式人工草稿')
            transport = model_input(bundle)
            metadata['transportInputHash'] = digest(transport)
            metadata['auditInputCharacters'] = len(encode(bundle))
            metadata['modelInputCharacters'] = len(encode(transport))
            draft, metrics = model.generate(PROMPT, transport, SCHEMA)
            metadata.update(metrics)
        decisions = validate(draft, bundle)
        write = draft['write']
        with store.db:
            store.db.execute('BEGIN IMMEDIATE')
            revision = store.db.execute('SELECT revision FROM scopes WHERE id=?', (scope,)).fetchone()[0]
            if revision != bundle['scopeRevision'] or store._episode(scope, episode)['status'] != 'SEALED':
                raise Invalid('巩固期间输入状态变化，拒绝过期结果')
            mapping = {n['id']: n['id'] for n in bundle['knownNodes']}
            mapping.update({n['key']: 'node_'+digest([run, n['key']])[:24] for n in write['entities']+write['memories']})
            reused = set()
            for n in write['entities']:
                if n['speakerId']:
                    prior = store.db.execute('SELECT id FROM nodes WHERE scope=? AND speaker_id=?', (scope, n['speakerId'])).fetchone()
                    if prior:
                        if prior[0] not in mapping:
                            raise Invalid('发言者实体来自不可见话题，不能隐式引入')
                        mapping[n['key']] = prior[0]
                        reused.add(n['key'])
            for n in write['entities']+write['memories']:
                if n['key'] in reused:
                    continue
                memory = 'kind' in n
                store.db.execute('''INSERT INTO nodes(id,scope,episode,stage,type,kind,label,subject,status,evidence,used,run_id,speaker_id)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (mapping[n['key']], scope, episode, 'LONG_TERM', 'MEMORY' if memory else n['type'],
                  n.get('kind', 'ENTITY'), n['text'] if memory else n['label'], mapping[n['subject']] if memory else None,
                  'CURRENT', encode(n['evidence']), encode(n.get('usedMemoryIds', [])), run, n.get('speakerId')))
            promote = {i for i, d in decisions.items() if d['action'] == 'KEEP'}
            promote.update(mapping[n['subject']] for n in write['memories'])
            promote.update(mapping[n['key']] for n in write['entities'])
            promote.update(mapping[e[k]] for e in write['associations'] for k in ('source', 'target'))
            for ident in draft.get('retainAssociations', []):
                old = store.db.execute('SELECT source,target FROM edges WHERE id=? AND scope=?', (ident, scope)).fetchone()
                if old is None:
                    raise Invalid('保留关联已不存在或scope不匹配')
                promote.update(old)
                store.db.execute('INSERT INTO edge_publications VALUES(?,?)', (ident, run))
            for ident in list(promote):
                subject = store.db.execute('SELECT subject FROM nodes WHERE id=?', (ident,)).fetchone()[0]
                if subject:
                    promote.add(subject)
            for ident in promote:
                store.db.execute("UPDATE nodes SET stage='LONG_TERM' WHERE id=? AND scope=?", (ident, scope))
            for ident, decision in decisions.items():
                if decision['action'] in ('ARCHIVE', 'MERGE'):
                    store.db.execute("UPDATE nodes SET stage='ARCHIVED',status=? WHERE id=?", ('CONSOLIDATED' if decision['action'] == 'MERGE' else 'ARCHIVED', ident))
            for n in write['memories']:
                for old in n['supersedes']:
                    store.db.execute("UPDATE nodes SET status='SUPERSEDED' WHERE id=?", (old,))
                    store.db.execute('INSERT INTO revisions VALUES(?,?,?)', (old, mapping[n['key']], run))
            for index, edge in enumerate(write['associations']):
                store.db.execute('INSERT INTO edges VALUES(?,?,?,?,?,?,?,?,?)', (f'{run}:edge:{index}', scope,
                    mapping[edge['source']], mapping[edge['target']], edge['relation'], edge['strength'], encode(edge['evidence']), edge['rationale'], run))
            # Mentions from kept nodes/new nodes are deliberately released; other temporary mentions stay local.
            events = {e['id']: e for e in bundle['events']+bundle['contextEvents']}
            mentions = {}
            # A shared person's injected evidence is episode-augmented: it includes
            # deferred memories too. Release kept MEMORY evidence, not that aggregate.
            sources = [n for n in bundle['knownNodes'] if n['type'] == 'MEMORY' and n['id'] in promote] + [
                {'id': mapping[n['key']], 'subject': mapping[n['subject']] if 'kind' in n else None, 'evidence': n['evidence']}
                for n in write['entities']+write['memories']]
            for n in sources:
                ident = n.get('subject') or n['id']
                binding = store.db.execute('SELECT speaker_id FROM nodes WHERE id=?', (ident,)).fetchone()[0]
                if binding:
                    mentions.setdefault(ident, {}).update({encode(e): e for e in n['evidence'] if e['eventId'] in events and events[e['eventId']]['speaker'] == binding})
            for ident, refs in mentions.items():
                if refs:
                    store.db.execute('INSERT INTO entity_mentions VALUES(?,?,?,?,?)', (ident, scope, episode, run, encode(list(refs.values()))))
            deferred = sum(d['action'] == 'DEFER' for d in decisions.values())
            store.db.execute("UPDATE nodes SET stage='ARCHIVED' WHERE scope=? AND episode=? AND stage='TEMPORARY' AND status='SUPERSEDED'", (scope, episode))
            remaining = store.db.execute("SELECT COUNT(*) FROM nodes WHERE scope=? AND episode=? AND stage='TEMPORARY' AND type='MEMORY' AND status='CURRENT'", (scope, episode)).fetchone()[0]
            store.db.execute('UPDATE episodes SET status=? WHERE scope=? AND id=?', ('SEALED' if remaining else 'CONSOLIDATED', scope, episode))
            store.db.execute('UPDATE scopes SET revision=revision+1 WHERE id=?', (scope,))
            store.db.execute("UPDATE writes SET status='COMMITTED',output=?,metadata=? WHERE id=?", (encode(draft), encode(metadata), run))
            store.db.execute("UPDATE consolidations SET status='COMMITTED',decisions=? WHERE write_id=?", (encode(draft['decisions']), run))
        return {'writeId': run, 'mapping': mapping, 'decisions': draft['decisions'], 'deferred': deferred, 'remainingTemporary': remaining,
                'memoriesCreated': len(write['memories']), 'metadata': metadata, 'episode': store._episode(scope, episode)}
    except Exception as error:
        with store.db:
            store.db.execute("UPDATE writes SET status='FAILED',output=?,metadata=?,error=? WHERE id=?", (encode(draft) if draft is not None else None, encode(metadata), str(error), run))
            store.db.execute("UPDATE consolidations SET status='FAILED' WHERE write_id=?", (run,))
        raise
