"""Consistent project-local SQLite backup; no Docker CLI is needed."""
from datetime import datetime
from pathlib import Path
import json
import sqlite3
import zipfile

root=Path(__file__).resolve().parents[1]
source=root/'native-data'/'data'/'opentutor.db'
if not source.is_file():
    raise SystemExit('Local learning database not found; nothing was overwritten.')
folder=root/'local-backups'
folder.mkdir(exist_ok=True)
target=folder/('opentutor-native-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src, sqlite3.connect(target) as dest:
    src.backup(dest)
    assert dest.execute('PRAGMA quick_check').fetchone()[0]=='ok'
archive=target.with_suffix('.zip')
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as bundle:
    bundle.write(target,'native-data/data/opentutor.db')
    for folder_name in ('uploads','logs'):
        for file in sorted((root/'native-data'/folder_name).rglob('*')):
            if file.is_file(): bundle.write(file,file.relative_to(root).as_posix())
    config=root/'native-data'/'settings.env'
    if config.is_file(): bundle.write(config,'native-data/settings.env')
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
print(json.dumps({'database_backup':str(target),'complete_backup':str(archive),'verified':True},ensure_ascii=False))
