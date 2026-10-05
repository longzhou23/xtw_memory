"""Start a standalone gateway or use its local Bot-independent client."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'router_deploy'))
sys.path.insert(0,str(ROOT/'research-mvp'))
from research_memory.chat_gateway import Inbox, make_server, run_worker
from research_memory.contracts import Invalid
from research_memory.providers import CodexProvider
from xtw_router.frozen import FrozenTwoJudgeCPU, INPUT_VERSION


def local_token(path, create=False):
    path=Path(path)
    if create:
        path.parent.mkdir(parents=True,exist_ok=True)
        try:
            descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor,'w') as stream:stream.write(secrets.token_urlsafe(32)+'\n')
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
            raise ValueError('令牌须为本人所有的私有文件（权限600）')
        token=stream.read(201).strip()
    if not 32<=len(token)<=200 or any(c.isspace() for c in token):
        raise ValueError('本地令牌长度或格式不合法')
    return token


def load_messages(path):
    path=Path(path)
    with path.open() as stream:
        first=stream.read(1)
        while first and first.isspace():first=stream.read(1)
        stream.seek(0)
        if first=='[':
            if path.stat().st_size>4194304:raise ValueError('大文件请用逐行JSONL')
            rows=json.load(stream)
            if not isinstance(rows,list):raise ValueError('需要消息数组')
            yield from rows
        else:
            for line in stream:
                if line.strip():yield json.loads(line)


def main():
    parser=argparse.ArgumentParser(description='本地群聊消息网关：独立于尚未完成的Bot harness')
    parser.add_argument('--db',default=str(ROOT/'research-mvp/var/chat-light.sqlite3'))
    parser.add_argument('--token-file',help='默认数据库路径加.token，客户端直接读取，不打印令牌')
    parser.add_argument('--url',default='http://127.0.0.1:8767')
    commands=parser.add_subparsers(dest='command',required=True)
    serve=commands.add_parser('serve');serve.add_argument('--port',type=int,default=8767)
    serve.add_argument('--writer',choices=['codex'],required=True,help='显式启用现有外部记忆写入模型')
    serve.add_argument('--seal',default=os.environ.get('XTW_MEMORY_SEAL'),help='完整模型封存 JSON；也可设置 XTW_MEMORY_SEAL')
    ingest=commands.add_parser('import');ingest.add_argument('file');ingest.add_argument('--close',action='store_true')
    for name in ('jobs','summary','memories'):
        item=commands.add_parser(name);item.add_argument('scope');item.add_argument('--after',type=int,default=0);item.add_argument('--limit',type=int,default=50)
    commands.add_parser('status')
    commands.add_parser('stop')
    item=commands.add_parser('job');item.add_argument('id',type=int)
    item=commands.add_parser('close');item.add_argument('scope');item.add_argument('--id',required=True)
    item=commands.add_parser('retry');item.add_argument('id',type=int)
    item=commands.add_parser('review');item.add_argument('id',type=int);item.add_argument('--confirm-ended',action='store_true',required=True)
    args=parser.parse_args()
    token_path=args.token_file or args.db+'.token'
    accepted_count=0
    def emit(value):print(json.dumps(value,ensure_ascii=False,indent=2),flush=True)
    try:
        if args.command=='serve':
            if not args.seal:
                parser.error('serve 需要 --seal 或 XTW_MEMORY_SEAL 指定本地模型封存文件')
            if not Path(args.seal).is_file():
                parser.error('--seal 指定的模型封存文件不存在')
            token=local_token(token_path,create=True)
            with Path(args.seal).open('rb') as stream:seal_hash=hashlib.file_digest(stream,'sha256').hexdigest()
            inbox=Inbox(args.db,identity={'routerSealSha256':seal_hash,'threshold':.50,'inputVersion':INPUT_VERSION,
                                         'writer':'codex-gpt-6.1-sol-medium-openai-180s-zero-retries'})
            server=make_server(inbox,token,args.port);stop=threading.Event()
            scorer=lambda:FrozenTwoJudgeCPU(args.seal,max_requests=None,max_passes=None,max_seconds=None,trace_limit=8)
            writer=lambda:CodexProvider(model='gpt-6.1-sol',model_provider='openai',timeout=180,zero_retries=True,reasoning_effort='medium')
            thread=threading.Thread(target=run_worker,args=(inbox,scorer,writer,stop));thread.start()
            emit({'listening':f'http://127.0.0.1:{server.server_port}','db':inbox.path,'tokenFile':str(Path(token_path).resolve()),'worker':'LOADING'})
            try:server.serve_forever(poll_interval=.2)
            except KeyboardInterrupt:pass
            finally:
                server.server_close();stop.set()
                if thread.is_alive():emit({'stopping':'停止接收；等待当前有界模型调用结束，未处理队列留在数据库'})
                thread.join()
            return 0
        target=urllib.parse.urlsplit(args.url)
        if target.scheme!='http' or target.hostname not in ('127.0.0.1','localhost') or target.username or target.password or target.path not in ('','/'):
            raise ValueError('客户端仅连接本地回环HTTP网关')
        token=local_token(token_path)
        def request(path,body=None):
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
            data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None
            with urllib.request.urlopen(urllib.request.Request(args.url.rstrip('/')+path,data,headers),timeout=10) as response:return json.load(response)
        if args.command=='import':
            count=0;groups=set()
            with Path(args.file).open('rb') as stream:fingerprint=hashlib.file_digest(stream,'sha256').hexdigest()[:24]
            for row in load_messages(args.file):
                result=request('/api/messages',row);count+=1;accepted_count=count;groups.add(result['scope'])
            closes=[]
            if args.close:
                for scope in sorted(groups):closes.append(request('/api/close',{'scope':scope,'id':'import-'+fingerprint}))
            emit({'accepted':count,'groups':sorted(groups),'closeReceipts':closes,'meaning':'已落盘接收；用status/job确认整理结果'})
        elif args.command in ('jobs','summary','memories'):
            query=urllib.parse.urlencode({'scope':args.scope,'after':args.after,'limit':args.limit})
            emit(request('/api/'+args.command+'?'+query))
        elif args.command=='status':emit(request('/health'))
        elif args.command=='stop':emit(request('/api/stop',{'confirm':True}))
        elif args.command=='job':emit(request('/api/job?id='+str(args.id)))
        elif args.command=='close':emit(request('/api/close',{'scope':args.scope,'id':args.id}))
        elif args.command=='retry':emit(request('/api/retry',{'jobId':args.id}))
        else:emit(request('/api/review',{'jobId':args.id,'confirmEnded':args.confirm_ended}))
        return 0
    except urllib.error.HTTPError as error:
        with error:emit({'error':json.load(error),'httpStatus':error.code,'acceptedBeforeError':accepted_count,'meaning':'导入此前已接收的条目仍保留；可重导同一文件'})
        return 2
    except (OSError,ValueError,Invalid) as error:
        emit({'error':str(error),'acceptedBeforeError':accepted_count});return 2


if __name__=='__main__':raise SystemExit(main())
