"""Audit and export a clean source ZIP without changing Git index or publishing.

Uses Git's own ignore rules. No private values are included in reports.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GIT=['git','-c',f'safe.directory={ROOT.as_posix()}']

def git(*args,input=None):
    return subprocess.check_output([*GIT,*args],cwd=ROOT,input=input)

def public_files():
    names=set(git('ls-files','-co','--exclude-standard','-z').decode('utf-8').split('\0'))-{''}
    raw='\0'.join(sorted(names)).encode()+b'\0'
    ignored=subprocess.run([*GIT,'check-ignore','--no-index','-z','--stdin'],cwd=ROOT,input=raw,
                           stdout=subprocess.PIPE,check=False)
    if ignored.returncode not in (0,1):raise RuntimeError('Unable to read Git ignore rules')
    names-=set(ignored.stdout.decode('utf-8').split('\0'))
    files=[]
    for name in sorted(names):
        path=ROOT/name
        if not path.exists():continue
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError('Unsafe source path: '+name)
        if path.is_file():files.append(name)
    return files

def credentials():
    values={}
    for name in ('.env','apps/api/.env','native-data/settings.env'):
        path=ROOT/name
        if not path.exists():continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            m=re.match(r'^\s*([A-Z][A-Z_0-9]*)\s*=\s*(.*?)\s*$',line)
            if not m or not re.search(r'API_KEY|SECRET_KEY|ACCESS_TOKEN|GITHUB_TOKEN|PASSWORD|ENCRYPTION_KEY',m[1]):continue
            value=m[2].strip().strip('\"\'')
            if len(value)<16 or re.search(r'^(?:change[-_ ]?me|your[-_ ]|example|placeholder|dev[-_])',value,re.I):continue
            values[value.encode('utf-8')]=m[1]
    return values

def sensitive_fields_in_template(data):
    issues=[]
    for number,line in enumerate(data.decode('utf-8-sig').splitlines(),1):
        m=re.match(r'^\s*([A-Z][A-Z_0-9]*)\s*=\s*(.*?)\s*$',line)
        if m and re.search(r'(?:API_KEY|ACCESS_TOKEN|GITHUB_TOKEN|DATABASE_PASSWORD)$',m[1]) and m[2].strip().strip('\"\''):
            issues.append({'line':number,'field':m[1],'kind':'nonempty_template_credential'})
    return issues

def audit(files,*,history=False):
    secrets=credentials();findings=[];total=0
    forbidden={'.db','.sqlite','.sqlite3','.log','.exe','.zip'}
    for name in files:
        path=ROOT/name;data=path.read_bytes();total+=len(data)
        if path.suffix.lower() in forbidden or any(p in ('native-data','local-backups','.runtime','node_modules','.git','.venv-win','.next','__pycache__','source-release','tmp') for p in path.relative_to(ROOT).parts):
            findings.append({'path':name,'kind':'private_or_generated_file'})
        for value,field in secrets.items():
            if value in data:findings.append({'path':name,'field':field,'kind':'current_private_credential'})
        if path.name=='.env.example':
            findings.extend({'path':name,**i} for i in sensitive_fields_in_template(data))
    result={'ok':not findings,'source_files':len(files),'source_bytes':total,'findings':findings}
    if history:
        objects=git('rev-list','--objects','--all').decode('utf-8').splitlines()
        process=subprocess.Popen([*GIT,'cat-file','--batch'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        matches=[];checked=0
        try:
            for row in objects:
                oid,_,name=row.partition(' ')
                process.stdin.write((oid+'\n').encode());process.stdin.flush()
                header=process.stdout.readline().decode().split()
                if len(header)!=3:raise RuntimeError('Unable to inspect a Git object')
                size=int(header[2]);remaining=size;found=set();tail=b''
                # Chunk large objects to keep memory bounded and scan across chunk boundaries.
                overlap=max([len(s) for s in secrets]+[1])-1
                while remaining:
                    chunk=process.stdout.read(min(remaining,1024*1024));remaining-=len(chunk)
                    if not chunk:raise RuntimeError('Truncated Git object')
                    block=tail+chunk
                    for value,field in secrets.items():
                        if value in block:found.add(field)
                    tail=block[-overlap:] if overlap else b''
                process.stdout.read(1)
                if header[1]=='blob':checked+=1
                if found:matches.append({'object':oid,'path':name,'fields':sorted(found)})
        finally:
            process.stdin.close();process.wait(timeout=10);process.stdout.close()
        result['history']={'blobs_checked':checked,'current_private_credential_matches':matches}
        result['ok']=result['ok'] and not matches
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history',action='store_true',help='Check reachable history for current local credentials')
    parser.add_argument('--zip',action='store_true',help='Create ignored source-release/OpenTutor-source.zip after a successful audit')
    parser.add_argument('--web',action='store_true',help='Also group sources into at most 90 files per GitHub browser upload')
    args=parser.parse_args()
    files=public_files();result=audit(files,history=args.history)
    folder=ROOT/'source-release';folder.mkdir(exist_ok=True)
    if args.zip and result['ok']:
        target=folder/'OpenTutor-source.zip'
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as bundle:
            for name in files:bundle.write(ROOT/name,'OpenTutor/'+name)
        with zipfile.ZipFile(target) as bundle:
            if bundle.testzip() is not None:raise RuntimeError('Source archive verification failed')
            assert len(bundle.namelist())==len(files)
        result['archive']={'path':str(target),'bytes':target.stat().st_size}
    if args.web and result['ok']:
        target=folder/'OpenTutor-GitHub-web-upload.zip'
        groups=[files[index:index+90] for index in range(0,len(files),90)]
        instructions=("GitHub 网页上传说明\n\n先解压本包。按照 batch-01、batch-02…逐批上传。\n每次打开一个批次文件夹，把里面的文件和目录上传到同一个仓库的根目录。\n不要把 batch-XX 这个外层目录本身上传，也不要上传 ZIP 文件代替源码。\n每次上传后提交，再处理下一批；同名目录内的不同文件会逐步补齐。\n全部批次完成后，仓库根目录应该直接看到 README.md、apps、scripts 等。\n包含隐藏名称的 .github 和 .env.example，也要上传。\n不包含你的实际 API、数据库、个人资料或 Git 历史。\n\nGitHub 官方限制：每次最多 100 个文件，每个文件不超过 25 MiB；本包按每批最多 90 个文件分组。\nhttps://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository\n")
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr('先读我.txt',instructions)
            for number,group in enumerate(groups,1):
                for name in group:bundle.write(ROOT/name,f'batch-{number:02d}/'+name)
        with zipfile.ZipFile(target) as bundle:
            if bundle.testzip() is not None:raise RuntimeError('Browser source archive verification failed')
        result['browser_upload']={'path':str(target),'batches':len(groups),'files_per_batch':90,'bytes':target.stat().st_size}
    (folder/'source-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    if not result['ok']:raise SystemExit(1)

if __name__=='__main__':main()
