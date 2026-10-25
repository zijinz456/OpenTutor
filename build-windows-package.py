"""Build a self-contained Windows x64 installer from the verified local runtimes.

Run a production Next build with OPENTUTOR_PACKAGE=1 first. No Git state is changed.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'source-release'
VERSION='1.2.0'
MAGIC=b'OpenTutorPkgV1!!'


def source_module():
    spec=importlib.util.spec_from_file_location('source_bundle',ROOT/'scripts/source-bundle.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def runtime_files(base:Path):
    """No cached bytecode, development executables, or links to outside the runtime."""
    for path in sorted(base.rglob('*')):
        if any(part in {'__pycache__','.pytest_cache','.cache'} for part in path.relative_to(base).parts):continue
        if path.suffix in {'.pyc','.pyo'}:continue
        if path.is_symlink() or getattr(path,'is_junction',lambda:False)():
            raise ValueError('Runtime contains a filesystem link: '+str(path))
        if path.is_file():yield path


def build():
    OUTPUT.mkdir(exist_ok=True)
    source=source_module();public=source.public_files();audit=source.audit(public)
    if not audit['ok']:raise ValueError('Source audit failed; inspect source-audit.json')
    standalone=ROOT/'apps/web/.next/standalone'
    required=[standalone/'apps/web/server.js',ROOT/'OpenTutor.exe',ROOT/'.runtime/node/node.exe',ROOT/'.runtime/python/python.exe',ROOT/'scripts/windows/Node-LICENSE.txt']
    for path in required:
        if not path.is_file():raise ValueError('Required distribution input missing: '+str(path))
    # Make this independently runnable build usable in the development checkout too.
    shutil.copytree(ROOT/'apps/web/.next/static',standalone/'apps/web/.next/static',dirs_exist_ok=True)
    if (ROOT/'apps/web/public').exists():shutil.copytree(ROOT/'apps/web/public',standalone/'apps/web/public',dirs_exist_ok=True)
    inputs:dict[str,Path|bytes]={}
    def add(name:str,path:Path|bytes):
        key=Path(name).as_posix()
        if key in inputs:raise ValueError('Duplicate package path: '+key)
        inputs[key]=path
    for name in public:
        if name.startswith('apps/api/') or name.startswith('scripts/') or name.startswith('docs/') or name in {'LICENSE','README.md','README.en.md','README.zh-CN.md','.env.example','Start-OpenTutor.cmd','Stop-OpenTutor.cmd','Backup-OpenTutor.cmd'}:
            add(name,ROOT/name)
    for path in runtime_files(ROOT/'.runtime/python'):
        add(path.relative_to(ROOT).as_posix(),path)
    for path in runtime_files(ROOT/'apps/api/.venv-win/Lib/site-packages'):
        relative=path.relative_to(ROOT/'apps/api/.venv-win/Lib/site-packages')
        if relative.parts[0] in {'pip','setuptools','wheel'} or relative.parts[0].startswith(('pip-','setuptools-','wheel-')):continue
        add('.runtime/python/Lib/site-packages/'+relative.as_posix(),path)
    add('.runtime/node/node.exe',ROOT/'.runtime/node/node.exe')
    add('.runtime/node/LICENSE.txt',ROOT/'scripts/windows/Node-LICENSE.txt')
    for path in runtime_files(standalone):
        if path.name.startswith('.env'):raise ValueError('An environment file was traced into the web build')
        add('apps/web/.next/standalone/'+path.relative_to(standalone).as_posix(),path)
    # The cleaner checks this source marker; no development node_modules are shipped.
    add('apps/web/package.json',ROOT/'apps/web/package.json')
    add('OpenTutor.exe',ROOT/'OpenTutor.exe')
    for path in (ROOT/'apps/web/node_modules').rglob('*'):
        if path.is_file() and not path.is_symlink() and (path.name.upper().startswith(('LICENSE','LICENCE','COPYING','NOTICE'))):
            add('THIRD_PARTY/node/'+path.relative_to(ROOT/'apps/web/node_modules').as_posix(),path)
    add('使用说明.txt',(ROOT/'docs/guides/windows-native-support.md').read_bytes())
    add('THIRD_PARTY/README.txt',b'OpenTutor is distributed under the root LICENSE. Python and its packages retain their license files under .runtime/python. Node.js license: .runtime/node/LICENSE.txt. npm dependency notices: THIRD_PARTY/node. No personal API key or learning records are included.\n')
    secrets=source.credentials();manifest=[];blocked=[]
    for name,item in sorted(inputs.items()):
        parts=Path(name).parts
        if any(part in {'native-data','local-backups','.git','.venv-win'} for part in parts) or Path(name).suffix.lower() in {'.db','.sqlite','.sqlite3','.log'} or (Path(name).name.startswith('.env') and Path(name).name!='.env.example'):
            blocked.append({'path':name,'kind':'private_file'});continue
        data=item if isinstance(item,bytes) else item.read_bytes()
        for value,field in secrets.items():
            if value in data:blocked.append({'path':name,'kind':'private_credential','field':field})
        manifest.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    if blocked:
        (OUTPUT/'distribution-audit.json').write_text(json.dumps({'ok':False,'findings':blocked},ensure_ascii=False,indent=2),encoding='utf-8')
        raise ValueError('Distribution privacy audit failed')
    metadata={'application':'OpenTutor','version':VERSION,'platform':'windows-x64','files':manifest,'personal_data_included':False}
    add('distribution.json',(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    payload=OUTPUT/'OpenTutor-windows-payload.zip'
    with zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,item in sorted(inputs.items()):
            if isinstance(item,bytes):archive.writestr(name,item)
            else:archive.write(item,name)
    with zipfile.ZipFile(payload) as archive:
        if archive.testzip():raise ValueError('Payload ZIP is corrupt')
    csc=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    stub=OUTPUT/'OpenTutor-setup-stub.exe'
    subprocess.run([str(csc),'/nologo','/target:winexe','/platform:x64','/optimize+',
        '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.IO.Compression.dll',
        '/reference:System.IO.Compression.FileSystem.dll','/win32icon:'+str(ROOT/'scripts/windows/OpenTutor.ico'),
        '/out:'+str(stub),str(ROOT/'scripts/windows/Setup.cs')],check=True)
    setup=OUTPUT/f'OpenTutor-Setup-{VERSION}-win-x64.exe'
    with payload.open('rb') as payload_stream:digest=hashlib.file_digest(payload_stream,'sha256').digest()
    with setup.open('wb') as stream:
        with stub.open('rb') as source_stream:shutil.copyfileobj(source_stream,stream)
        with payload.open('rb') as source_stream:shutil.copyfileobj(source_stream,stream)
        stream.write(struct.pack('<q',payload.stat().st_size)+digest+MAGIC)
    result={'ok':True,'version':VERSION,'platform':'windows-x64','installer':setup.name,'installer_bytes':setup.stat().st_size,'installed_bytes':sum(item['bytes'] for item in manifest),'files':len(inputs),'sha256':hashlib.file_digest(setup.open('rb'),'sha256').hexdigest(),'personal_data_included':False}
    (OUTPUT/'distribution-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.parse_args();build()
