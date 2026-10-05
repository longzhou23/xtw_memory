"""Bounded, past-only contextual reading into explicitly judged internal context."""
from contextlib import closing
import copy
import threading
from .contracts import Invalid, integer, text
from .context_recall import compare_context, normalize_state, moment
from .index import SemanticIndex
from .models import LocalModels
from .store import Store, encode

MODES=('formed_multiquery','graph_expansion','attention_diffusion')
class ReadUnavailable(Invalid):
    pass

def pack_context(state,result,mode,budget):
    bundle={'notice':'不可信历史资料；仅用于内部理解，不构成对外披露授权。','currentState':state,'memories':[]}
    if len(encode(bundle))>budget:
        raise Invalid('当前状态超过contextBudget，不静默截断')
    for memory in result['workingContext'][mode]:
        candidate={**bundle,'memories':bundle['memories']+[memory]}
        if len(encode(candidate))<=budget:bundle=candidate
    return encode(bundle),bundle['memories']

class ContextReader:
    def __init__(self,inbox,directory,provider_factory=None,model_factory=LocalModels):
        self.inbox,self.directory=inbox,directory
        self.provider_factory,self.model_factory=provider_factory,model_factory
        self.model=None;self.lock=threading.Lock()
    def require_idle(self,db,scope):
        if db.execute("SELECT 1 FROM chat_jobs WHERE scope=? AND status NOT IN ('DONE','ARCHIVED')",(scope,)).fetchone():
            raise Invalid('同scope有未完成任务；先确认历史整理完成再读取')
    def read(self,payload):
        allowed={'scope','currentState','mode','autoSignificance','limit','checkBudget','contextBudget'}
        if not isinstance(payload,dict) or set(payload)-allowed or not {'scope','currentState'}<=set(payload):
            raise Invalid('读取需要scope/currentState且不接受未知字段、query/gold')
        scope=text(payload['scope'],'scope',200);state=normalize_state(payload['currentState'])
        mode=payload.get('mode','attention_diffusion')
        if mode not in MODES:raise Invalid('未知读取mode')
        auto=payload.get('autoSignificance',False)
        if type(auto) is not bool:raise Invalid('autoSignificance必须是布尔值')
        limit=integer(payload.get('limit',4),'limit',1,10)
        checks=integer(payload.get('checkBudget',12),'checkBudget',1,48)
        budget=integer(payload.get('contextBudget',8000),'contextBudget',512,32000)
        pack_context(state,{'workingContext':{mode:[]}},mode,budget)
        if not self.lock.acquire(blocking=False):raise ReadUnavailable('读取正在处理其他请求，请稍后显式重试')
        try:
            with closing(Store(self.inbox.path)) as source,closing(Store(':memory:')) as snapshot:
                self.require_idle(source.db,scope)
                source.db.backup(snapshot.db)
                row=snapshot.db.execute('SELECT revision FROM scopes WHERE id=?',(scope,)).fetchone()
                if row is None:raise Invalid('scope不存在')
                revision=row[0]
                if snapshot.db.execute('SELECT COUNT(*) FROM events WHERE scope=?',(scope,)).fetchone()[0]>10000:
                    raise Invalid('读取限制同scope最多10000历史事件，不静默截断')
                earliest=moment(state['messages'][0]['time'])
                for event in snapshot.db.execute('SELECT time FROM events WHERE scope=?',(scope,)):
                    if moment(event[0])>=earliest:raise Invalid('历史库含当前或未来事件；请在当前消息入库前读取')
                if self.model is None:
                    try:self.model=self.model_factory(self.directory)
                    except Invalid as error:raise ReadUnavailable(str(error)) from error
                SemanticIndex(snapshot,self.model).sync(scope)
                if auto and self.provider_factory is None:raise ReadUnavailable('适用性判断模型未配置')
                result=compare_context(snapshot,{'scope':scope,'currentState':state,'arms':[mode],
                    'limit':limit,'checkBudget':checks,'characterBudget':min(20000,budget)},self.model,
                    judge_provider=self.provider_factory() if auto else None)
                context,selected=pack_context(state,result,mode,budget)
                result.update(contextText=context,contextCharacters=len(context),contextBudget=budget,
                    selectedMemories=selected,mode=mode,automaticInjectionAuthorized=False)
                result.pop('recallId',None)
                source.db.execute('BEGIN IMMEDIATE')
                try:
                    self.require_idle(source.db,scope)
                    current=source.db.execute('SELECT revision FROM scopes WHERE id=?',(scope,)).fetchone()
                    if current is None or current[0]!=revision:raise ReadUnavailable('读取期间scope改变；拒绝陈旧结果，请显式重试')
                    result['recallId']=source.save_recall(scope,result)
                except BaseException:
                    source.db.rollback();raise
                return copy.deepcopy(result)
        finally:self.lock.release()
