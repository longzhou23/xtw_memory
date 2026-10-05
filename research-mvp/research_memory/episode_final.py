"""CLOSED Episode archive to new durable cognitive nodes, one atomic publication.

Episode lifecycle never depends on this task's result. Historical Temporary
records stay archived; FORMED_WITH is not interpreted as a semantic relation.
"""
import copy
import uuid

from .contracts import Invalid, WRITE_SCHEMA, STRING, array, obj, shape, validate_write
from .providers import WRITE_PROMPT
from .store import digest, encode
from .episode_runtime import snapshot, recalled, KINDS

FINAL_WRITE_SCHEMA = copy.deepcopy(WRITE_SCHEMA)
FINAL_WRITE_SCHEMA['properties']['memories']['items']['properties']['recordKind'] = {'type':'string','enum':KINDS}
FINAL_WRITE_SCHEMA['properties']['memories']['items']['required'].append('recordKind')
SCHEMA = obj({'write':FINAL_WRITE_SCHEMA,'temporaryDecisions':array(obj({
    'memoryId':STRING,'action':{'type':'string','enum':['USED','ARCHIVE','RETAIN_UNRESOLVED']},'reason':STRING}))})
PROMPT = WRITE_PROMPT + '''
本次是整个CLOSED Episode的最终长期整理，不是OPEN阶段的临时检查点。
events是该Episode完整原文，包括未挤出的最后工作上下文；temporaryMemories是已归档的完整检查点历史，含被替代记录；formedWith仅是形成来源，不是事实因果或相似关系。
请回查原文，生成自足的长期经历/必要认知节点与有证据的三关系，不照抄临时概括当唯一证据。不要求每个检查点都长期保留，也不要求把整段经历压成一条摘要。
保留提出→修正→确认/取消的发展过程、请求与未完成状态、互动与玩笑；未解决的事实可按已知边界记录，不能猜完成。一次经历不自动概括成稳定性格或规则。
write中的节点全部为新长期输出；usedMemoryIds只声明参与形成的归档临时id或显式注入的长期记忆id。新增记忆也可直接来自events而不使用临时检查点。
temporaryDecisions逐一覆盖所有temporaryMemoryIds。USED表示至少一个write.memories声明使用该临时id；未使用的确定陈述ARCHIVE，未决与冲突RETAIN_UNRESOLVED并说明原因。两者都不修改原检查点，不重开Episode，没有DEFER。
不能给已归档临时id加语义关联或supersedes。supersedes只用于显式注入的CURRENT长期记忆中有明确同主体纠错的情况。FORMED_WITH来源与三关系分别存储，不能直接改名。
每个write.memories另声明recordKind（supported_statement/update/pending_reference/conflict），不得仅因关闭把未决变确定。未使用的pending_reference/conflict检查点必须RETAIN_UNRESOLVED。
记忆text只写有来源的陈述、经历、计划和必要的未知边界；不要把模型读过/未读过哪些材料、直接/继承来源的核对说明、内部事件或记忆ID写进正文。这些审计信息由已有来源字段和写入元数据保存。原聊天确实谈论这些内容时可如实记录，不机械删词。
“不能确定X”“不能猜成X”只表示证据不足，不表示“不是X”或“X已排除”。原文没有明确否定/排除时，身份和物品继续保持未知；可以记录有人提出不要猜测，但不能替他写成已确认的排除结论。
输出{write,temporaryDecisions}。只处理本Episode及明确注入的长期背景，输入不含未来问题。'''


def prepare(store, scope, episode, memory_ids=(), context_ids=()):
    state = snapshot(store,scope,episode)
    if state['episode']['status']!='CLOSED' or state['temporaryMemories']:
        raise Invalid('Final Consolidation要求CLOSED且已归档完整临时集合')
    if store.db.execute("SELECT 1 FROM consolidations WHERE scope=? AND episode=? AND status IN ('PENDING','COMMITTED')",(scope,episode)).fetchone():
        raise Invalid('该Episode已有在途或已提交的最终整理；不隐式重复调用')
    events = [dict(r) for r in store.db.execute('SELECT * FROM events WHERE scope=? AND episode=? ORDER BY seq LIMIT 501',(scope,episode))]
    if not events:
        raise Invalid('空Episode无需模型长期整理')
    known = recalled(store,scope,memory_ids)
    subjects = {n['subject'] for n in known.values()}
    # Authoritative speaker identities can be reused without recalling their memories.
    speakers = {e['speaker'] for e in events}
    for speaker in speakers:
        row = store.db.execute("SELECT id FROM nodes WHERE scope=? AND speaker_id=? AND stage='LONG_TERM'",(scope,speaker)).fetchone()
        if row:
            subjects.add(row[0])
    known.update(store.visible_nodes(scope,subjects,mentions=False))
    if subjects-set(known):
        raise Invalid('显式长期背景的主体不可见')
    if not isinstance(context_ids, (list, tuple)) or len(context_ids)>40 or len(set(context_ids))!=len(context_ids):
        raise Invalid('Final显式原文上下文最多40条且不能重复')
    context_ids = (set(context_ids) | {e['eventId'] for n in known.values() for e in n['evidence']}) - {e['id'] for e in events}
    context = []
    for ident in sorted(context_ids):
        row = store.db.execute('SELECT * FROM events WHERE scope=? AND id=?',(scope,ident)).fetchone()
        if row is None:
            raise Invalid('长期背景引用的原文缺失或跨scope')
        context.append(dict(row))
    # Context actors may have canonical identities even when they do not speak
    # in the new window. Inject bindings before the model redeclares them.
    context_subjects=set()
    for speaker in {e['speaker'] for e in context}:
        row=store.db.execute("SELECT id FROM nodes WHERE scope=? AND speaker_id=? AND stage='LONG_TERM'",(scope,speaker)).fetchone()
        if row and row[0] not in known:context_subjects.add(row[0])
    known.update(store.visible_nodes(scope,context_subjects,mentions=False))
    root_versions = {}
    root_ids = {ident for memory in state['history'] for ident in memory['sourceEventIds']}
    root_ids.update(ident for node in known.values() for ident in node.get('provenance',{}).get('sourceEventIds',[]))
    for ident in sorted(root_ids):
        row = store.db.execute('SELECT * FROM events WHERE scope=? AND id=?',(scope,ident)).fetchone()
        if row is None:
            raise Invalid('最终继承根原文缺失')
        root_versions[ident] = digest(dict(row))
    bundle = {'rootSourceVersions':root_versions,'scope':scope,'episode':state['episode'],'episodeRevision':state['revision'],
              'events':events,'contextEvents':context,'knownNodes':list(known.values()),
              'temporaryMemories':state['history'],'temporaryMemoryIds':[m['id'] for m in state['history']],
              'formedWith':state['formedWith'],'remainingWorkingContext':{'eventIds':[e['id'] for e in state['workingContext']], 'digest':digest(state['workingContext'])}}
    if len(events)>500 or len(context)>500 or len(known)+len(state['history'])>500 or len(encode(bundle).encode())>store.limits['per_input_bytes']:
        raise Invalid('最终整理超过500事件/节点或180000字符预算；不截断经历')
    return bundle


def validate(draft, bundle):
    shape(draft,SCHEMA)
    adapted = copy.deepcopy(draft['write'])
    for memory in adapted['memories']:
        del memory['recordKind']
    validation_bundle = copy.deepcopy(bundle)
    validation_bundle['knownNodes'].extend({'id':memory['id'],'type':'MEMORY','kind':'EPISODIC','label':memory['text'],
        'subject':memory['subjectRefs'][0],'status':'ARCHIVED','stage':'ARCHIVED','speakerId':None,'evidence':[],
        'usedMemoryIds':memory['memoryWriteProvenance']['usedMemoryIds']} for memory in bundle['temporaryMemories'])
    validate_write(adapted,validation_bundle)
    temporary = set(bundle['temporaryMemoryIds'])
    decisions = {d['memoryId']:d for d in draft['temporaryDecisions']}
    if len(decisions)!=len(draft['temporaryDecisions']) or set(decisions)!=temporary:
        raise Invalid('必须逐一说明完整归档临时集合的使用/保留历史去向')
    used = {i for n in draft['write']['memories'] for i in n['usedMemoryIds']} & temporary
    if {i for i,d in decisions.items() if d['action']=='USED'}!=used:
        raise Invalid('USED决定与新记忆的临时来源声明必须完全相等')
    if any(temporary.intersection(n['supersedes']) for n in draft['write']['memories']):
        raise Invalid('归档临时检查点不能作为长期纠错的supersedes目标')
    if any(e['source'] in temporary or e['target'] in temporary for e in draft['write']['associations']):
        raise Invalid('语义关联不能以归档临时检查点为端点；来源单独记录')
    for memory in bundle['temporaryMemories']:
        if memory['kind'] in ('pending_reference','conflict') and memory['id'] not in used and decisions[memory['id']]['action'] != 'RETAIN_UNRESOLVED':
            raise Invalid('未使用的未决/冲突必须保留为RETAIN_UNRESOLVED')
    return decisions


def finalize(store, scope, episode, model=None, draft=None, memory_ids=(), context_ids=()):
    import json
    prior = store.db.execute("SELECT w.id,w.output,w.metadata FROM writes w JOIN consolidations c ON c.write_id=w.id WHERE c.scope=? AND c.episode=? AND c.status='COMMITTED'",(scope,episode)).fetchone()
    if prior:
        metadata = json.loads(prior['metadata'])
        return {'writeId':prior['id'],'mapping':metadata['mapping'],'memoriesCreated':len(json.loads(prior['output'])['write']['memories']),
                'temporaryDecisions':json.loads(prior['output'])['temporaryDecisions'],'metadata':metadata,
                'episode':store._episode(scope,episode),'consolidationState':'COMMITTED','duplicates':1}
    store.db.execute('BEGIN IMMEDIATE')
    try:
        bundle = prepare(store,scope,episode,memory_ids,context_ids)
        run = 'final_'+uuid.uuid4().hex
        store.check_context_budget(pending_input=bundle)
        metadata = {'phase':'EPISODE_FINAL','provider':'reviewed-draft' if draft is not None else getattr(model,'name','missing'),
                    'inputHash':digest(bundle),'promptHash':digest(PROMPT),'schemaHash':digest(SCHEMA)}
        store.db.execute('INSERT INTO writes VALUES(?,?,?,?,?,?,?,?)',(run,scope,episode,'PENDING',encode(bundle),None,encode(metadata),None))
        store.db.execute('INSERT INTO consolidations VALUES(?,?,?,?,?)',(run,scope,episode,'PENDING',None))
        store.db.commit()
    except BaseException:
        store.db.rollback()
        raise
    try:
        if draft is None:
            if model is None:
                raise Invalid('请选择最终整理模型或显式人工草稿')
            draft,metrics = model.generate(PROMPT,copy.deepcopy(bundle),copy.deepcopy(SCHEMA))
            metadata['modelMetrics'] = copy.deepcopy(metrics)
        if len(encode(draft).encode())>store.limits['per_output_bytes']:
            raise Invalid('最终输出超过per_output_bytes')
        validate(draft,bundle)
        write = draft['write']
        store.db.execute('BEGIN IMMEDIATE')
        try:
            state = snapshot(store,scope,episode)
            if state['episode']['status']!='CLOSED' or state['revision']!=bundle['episodeRevision'] or state['history']!=bundle['temporaryMemories']:
                raise Invalid('最终整理的Episode快照变化，拒绝过期结果')
            raw = [dict(r) for r in store.db.execute('SELECT * FROM events WHERE scope=? AND episode=? ORDER BY seq',(scope,episode))]
            if raw!=bundle['events'] or {'eventIds':[e['id'] for e in state['workingContext']],'digest':digest(state['workingContext'])}!=bundle['remainingWorkingContext']:
                raise Invalid('最终整理的原始经历或剩余上下文变化，拒绝过期结果')
            for source in bundle['contextEvents']:
                current = store.db.execute('SELECT * FROM events WHERE scope=? AND id=?',(scope,source['id'])).fetchone()
                if current is None or dict(current)!=source:
                    raise Invalid('显式长期背景的原文来源在调用期间变化，拒绝过期结果')
            for ident, version in bundle['rootSourceVersions'].items():
                row = store.db.execute('SELECT * FROM events WHERE scope=? AND id=?',(scope,ident)).fetchone()
                if row is None or digest(dict(row)) != version:
                    raise Invalid('最终继承根原文版本变化')
            durable = [n for n in bundle['knownNodes'] if n['stage']=='LONG_TERM']
            if store.visible_nodes(scope,[n['id'] for n in durable],mentions=False)!={n['id']:n for n in durable}:
                raise Invalid('显式长期背景在最终整理期间变化，拒绝过期结果')
            mapping = {n['id']:n['id'] for n in durable}
            mapping.update({n['key']:'node_'+digest([run,n['key']])[:24] for n in write['entities']+write['memories']})
            reused = set()
            for n in write['entities']:
                if n.get('speakerId'):
                    prior = store.db.execute('SELECT id FROM nodes WHERE scope=? AND speaker_id=?',(scope,n['speakerId'])).fetchone()
                    if prior:
                        if prior[0] not in mapping:
                            raise Invalid('稳定身份在调用期间出现或位于旧临时模式；不隐式引入其来源')
                        mapping[n['key']]=prior[0];reused.add(n['key'])
            for n in write['entities']+write['memories']:
                if n['key'] in reused:
                    continue
                memory = 'kind' in n
                store.db.execute('''INSERT INTO nodes(id,scope,episode,stage,type,kind,label,subject,status,evidence,used,run_id,speaker_id)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(mapping[n['key']],scope,episode,('UNRESOLVED' if memory and n['recordKind'] in ('pending_reference','conflict') else 'LONG_TERM'),'MEMORY' if memory else n['type'],
                  n.get('kind','ENTITY'),n['text'] if memory else n['label'],mapping[n['subject']] if memory else None,
                  'CURRENT',encode(n['evidence']),encode(n.get('usedMemoryIds',[])),run,n.get('speakerId')))
            injected = {m['id']:m for m in bundle['temporaryMemories']}
            injected.update({n['id']:{'sourceEventIds':n.get('provenance',{}).get('sourceEventIds',[e['eventId'] for e in n['evidence']])} for n in durable if n['type']=='MEMORY'})
            for memory in write['memories']:
                direct = sorted({e['eventId'] for e in memory['evidence']})
                inherited = sorted({root for i in memory['usedMemoryIds'] for root in injected[i]['sourceEventIds']})
                provenance = {'recordKind':memory['recordKind'],'directSourceEventIds':direct,
                              'inheritedSourceEventIds':inherited,'sourceEventIds':sorted(set(direct+inherited)),
                              'usedMemoryIds':memory['usedMemoryIds']}
                store.db.execute('INSERT INTO episode_final_sources VALUES(?,?,?)',(mapping[memory['key']],encode(provenance),run))
                for target in memory['usedMemoryIds']:
                    store.db.execute('INSERT INTO episode_final_formed_with VALUES(?,?,?)',(mapping[memory['key']],target,run))
            for n in write['memories']:
                for old in n['supersedes']:
                    store.db.execute("UPDATE nodes SET status='SUPERSEDED' WHERE id=?",(old,))
                    store.db.execute('INSERT INTO revisions VALUES(?,?,?)',(old,mapping[n['key']],run))
            for number,edge in enumerate(write['associations']):
                store.db.execute('INSERT INTO edges VALUES(?,?,?,?,?,?,?,?,?)',(f'{run}:edge:{number}',scope,
                    mapping[edge['source']],mapping[edge['target']],edge['relation'],edge['strength'],encode(edge['evidence']),edge['rationale'],run))
            sources = {e['id']:e for e in bundle['events']+bundle['contextEvents']}
            mentions = {}
            for n in write['entities']+write['memories']:
                ident = mapping[n['subject']] if 'kind' in n else mapping[n['key']]
                binding = store.db.execute('SELECT speaker_id FROM nodes WHERE id=?',(ident,)).fetchone()[0]
                if binding:
                    mentions.setdefault(ident,{}).update({encode(e):e for e in n['evidence'] if sources[e['eventId']]['speaker']==binding})
            for ident,refs in mentions.items():
                if refs:
                    store.db.execute('INSERT INTO entity_mentions VALUES(?,?,?,?,?)',(ident,scope,episode,run,encode(list(refs.values()))))
            store.db.execute('UPDATE scopes SET revision=revision+1 WHERE id=?',(scope,))
            metadata['mapping'] = mapping
            store.db.execute("UPDATE writes SET status='COMMITTED',output=?,metadata=? WHERE id=?",(encode(draft),encode(metadata),run))
            store.db.execute("UPDATE consolidations SET status='COMMITTED',decisions=? WHERE write_id=?",(encode(draft['temporaryDecisions']),run))
            store.db.commit()
        except BaseException:
            store.db.rollback()
            raise
        return {'writeId':run,'mapping':mapping,'memoriesCreated':len(write['memories']),
                'temporaryDecisions':draft['temporaryDecisions'],'metadata':metadata,
                'episode':store._episode(scope,episode),'consolidationState':'COMMITTED'}
    except BaseException as error:
        with store.db:
            store.db.execute("UPDATE writes SET status='FAILED',output=?,metadata=?,error=? WHERE id=?",
                (encode(draft) if draft is not None else None,encode(metadata),str(error),run))
            store.db.execute("UPDATE consolidations SET status='FAILED' WHERE write_id=?",(run,))
        raise
