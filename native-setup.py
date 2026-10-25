"""Prepare a Windows source checkout using installed CPython 3.12 and Node.js 24.

Run: py -3.12 scripts/native-setup.py --node C:/Program Files/nodejs/node.exe
Downloads Python/npm dependencies and the matching Node.js license. No API key is requested.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]

def runtime_versions(node:Path):
    if os.name!='nt':raise ValueError('Windows x64 is required')
    if sys.version_info[:2]!=(3,12) or sys.maxsize<=2**32:raise ValueError('Use CPython 3.12 x64')
    if sys.implementation.name!='cpython':raise ValueError('Use CPython, not an alternative interpreter')
    version=subprocess.check_output([str(node),'--version'],text=True).strip()
    if not version.startswith('v24.'):raise ValueError('Use Node.js 24 x64')
    arch=subprocess.check_output([str(node),'-p','process.arch'],text=True).strip()
    if arch!='x64':raise ValueError('Use Node.js x64')
    return {'python':sys.version.split()[0],'node':version,'architecture':arch}

def prepare(node:Path,*,check=False):
    node=node.resolve(strict=True);versions=runtime_versions(node)
    npm=node.parent/'node_modules/npm/bin/npm-cli.js'
    if not npm.is_file():raise ValueError('Use a Node.js installation that includes npm')
    if check:return versions
    for target in (ROOT/'.runtime',ROOT/'apps/api/.venv-win'):
        if target.is_symlink() or getattr(target,'is_junction',lambda:False)():raise ValueError('Runtime target must not be a directory link')
    base=Path(sys.base_prefix).resolve();python=ROOT/'.runtime/python/python.exe'
    if not python.exists():
        destination=python.parent;destination.mkdir(parents=True,exist_ok=True)
        for name in ('python.exe','pythonw.exe','python3.dll','python312.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
            if (base/name).is_file():shutil.copyfile(base/name,destination/name)
        for name in ('DLLs','Lib','libs','include','tcl'):
            if (base/name).is_dir():shutil.copytree(base/name,destination/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('site-packages','__pycache__','*.pyc'))
    venv=ROOT/'apps/api/.venv-win'
    if not (venv/'Scripts/python.exe').is_file():subprocess.run([str(python),'-I','-m','venv',str(venv)],check=True)
    py=venv/'Scripts/python.exe'
    subprocess.run([str(py),'-I','-m','pip','install','-r',str(ROOT/'scripts/requirements-windows.lock')],check=True)
    target_node=ROOT/'.runtime/node/node.exe';target_node.parent.mkdir(parents=True,exist_ok=True)
    if node!=target_node.resolve():shutil.copyfile(node,target_node)
    license_file=ROOT/'scripts/windows/Node-LICENSE.txt'
    with urllib.request.urlopen('https://raw.githubusercontent.com/nodejs/node/'+versions['node']+'/LICENSE',timeout=30) as response:license_file.write_bytes(response.read())
    subprocess.run([str(node),str(npm),'--prefix',str(ROOT/'apps/web'),'ci'],check=True)
    env={**os.environ,'OPENTUTOR_PACKAGE':'1','NEXT_PUBLIC_API_URL':'http://127.0.0.1:8000/api','NEXT_TELEMETRY_DISABLED':'1'}
    subprocess.run([str(node),str(ROOT/'apps/web/node_modules/next/dist/bin/next'),'build',str(ROOT/'apps/web'),'--webpack'],cwd=ROOT,env=env,check=True)
    standalone=ROOT/'apps/web/.next/standalone/apps/web'
    shutil.copytree(ROOT/'apps/web/.next/static',standalone/'.next/static',dirs_exist_ok=True)
    if (ROOT/'apps/web/public').exists():shutil.copytree(ROOT/'apps/web/public',standalone/'public',dirs_exist_ok=True)
    subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/build-native-launcher.ps1')],check=True)
    subprocess.run([str(py),'-I','-X','utf8',str(ROOT/'scripts/native-init.py')],check=True)
    return {**versions,'ready':True,'start':'OpenTutor.exe'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node',type=Path,default=Path(shutil.which('node') or 'node.exe'))
    parser.add_argument('--check',action='store_true',help='Validate installed build tools without writing or installing')
    args=parser.parse_args();print(json.dumps(prepare(args.node,check=args.check),ensure_ascii=False))
