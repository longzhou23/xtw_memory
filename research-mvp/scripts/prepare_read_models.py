"""Download only frozen public BGE resources; no chat or credential access."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research_memory.models import HASHES
REPOSITORIES={
 'embedding':('Xenova/bge-small-zh-v1.5','75c43b069aac4d136ba6bc1122f995fedcfd2781'),
 'reranker':('Xenova/bge-reranker-base','280bcc27a84e0b898c251e06fddb25171bd9b101'),
}
def file_hash(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def prepare(directory,fetch=urllib.request.urlopen):
    root=Path(directory).resolve();root.mkdir(parents=True,exist_ok=True)
    manifest={'version':1,'models':{},'recipe':'cls-l2-query-prefix-v1;fp32-pair-logit;max-token-256;source-windows-v1','license':'BAAI BGE MIT'}
    for name,files in HASHES.items():
        repo,revision=REPOSITORIES[name];folder=root/name;folder.mkdir(exist_ok=True);saved={}
        for local,expected in files.items():
            target=folder/local
            if not target.exists():
                remote=('onnx/model_quantized.onnx' if name=='embedding' else 'onnx/model.onnx') if local.endswith('.onnx') else local
                partial=folder/(local+'.partial')
                with fetch(f'https://huggingface.co/{repo}/resolve/{revision}/{remote}',timeout=120) as response,partial.open('wb') as stream:
                    while block:=response.read(1024*1024):stream.write(block)
                if file_hash(partial)!=expected:raise ValueError(f'模型哈希不匹配：{name}/{local}；保留partial，未采用文件')
                partial.replace(target)
            if file_hash(target)!=expected:raise ValueError(f'已有模型哈希不匹配：{name}/{local}；不覆盖文件')
            saved[local]={'sha256':expected,'bytes':target.stat().st_size}
        manifest['models'][name]={'repository':repo,'revision':revision,'files':saved}
        print(f'已验证 {name}',flush=True)
    temporary=root/'manifest.json.partial';temporary.write_text(json.dumps(manifest,indent=2)+'\n');temporary.replace(root/'manifest.json')
    return manifest
def main():
    parser=argparse.ArgumentParser(description='下载并校验固定公开BGE读取模型，不读写聊天资料')
    parser.add_argument('--directory',type=Path,default=Path(__file__).resolve().parents[2]/'models/semantic')
    args=parser.parse_args();prepare(args.directory)
if __name__=='__main__':main()
