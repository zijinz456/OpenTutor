"""Remove only known, regenerable local caches; never source, dependencies or user data."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATHS = (
    "apps/web/.next/cache", ".pytest_cache", ".hypothesis",
    "apps/api/.pytest_cache", "source-release/ui-browser-review",
)

def redirected(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()

def inspect_cache(root, relative):
    if relative not in CACHE_PATHS:
        raise ValueError("Path is not an approved cache")
    target=root / relative
    for item in (target, *target.parents):
        if item == root: break
        if redirected(item): raise ValueError("Cache path contains a filesystem link")
    absolute=target.resolve()
    if absolute == root or not absolute.is_relative_to(root):
        raise ValueError("Cache path escapes the project")
    if not target.exists(): return None
    if not target.is_dir(): raise ValueError("Cache path is not a directory")
    size=count=0
    for folder, dirs, files in os.walk(target, followlinks=False):
        for name in dirs+files:
            if redirected(Path(folder)/name):
                raise ValueError("Cache contains a filesystem link")
        for name in files:
            size+=(Path(folder)/name).stat().st_size; count+=1
    return {"path":relative,"bytes":size,"files":count}

def cleanup(root=ROOT, *, apply=False):
    root=Path(root).resolve(strict=True)
    if not (root/"apps/api/main.py").is_file() or not (root/"apps/web/package.json").is_file():
        raise ValueError("Not an OpenTutor project directory")
    planned=[]; errors=[]; removed=[]
    for relative in CACHE_PATHS:
        try:
            item=inspect_cache(root,relative)
            if item: planned.append(item)
        except (ValueError,OSError) as exc:
            errors.append({"path":relative,"error":str(exc)})
    if apply:
        for item in planned:
            try:
                # Recheck immediately before deletion; the absolute target stays under this root.
                current=inspect_cache(root,item["path"])
                if current:
                    shutil.rmtree(root/item["path"])
                    removed.append(current)
            except (ValueError,OSError) as exc:
                errors.append({"path":item["path"],"error":str(exc)})
    entries=removed if apply else planned
    return {"ok":not errors,"applied":apply,"bytes":sum(i["bytes"] for i in entries),
            "files":sum(i["files"] for i in entries),"caches":entries,"errors":errors,
            "preserved":["source code","runtime dependencies","learning data","backups","logs"]}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true",help="Delete caches; otherwise only preview")
    args=parser.parse_args()
    result=cleanup(apply=args.apply)
    print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)
