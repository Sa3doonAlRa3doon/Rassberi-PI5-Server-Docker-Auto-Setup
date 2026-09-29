#!/usr/bin/env python3
"""One-time first-run preparation. No ports are published by Compose run."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess

os.umask(0o077)
# Ask Compose to parse .env; do not evaluate it as shell code or print values.
raw = subprocess.check_output(['docker','compose','config','--environment'], text=True)
env = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
def required(key):
    value = env.get(key, '')
    if not value or value == 'GENERATE':
        raise RuntimeError('Missing generated setting: ' + key)
    return value
def run(*args, input=None, capture=False):
    # Avoid subprocess exception repr containing output/secret material.
    result = subprocess.run(['docker','compose','run','--rm','--no-deps','-T', *args],
                            input=input, text=True, stdout=subprocess.PIPE if capture else None)
    if result.returncode:
        raise RuntimeError('Application preparation command failed; inspect the preceding log.')
    return result.stdout if capture else None
base = Path('/srv/docker/appdata/calibre-web/config')
db = base/'app.db'
pending = base/'.bootstrap-pending'
fresh = not db.exists()
if fresh and not pending.exists(): pending.touch(mode=0o600)
if fresh or pending.exists():
    # Official CLI initializes its own schema, hashes a supplied password, then exits.
    code = ("import subprocess,sys; password=sys.stdin.read().strip(); "
            "result=subprocess.run(['python3','/app/calibre-web/cps.py','-p','/config/app.db','-s','admin:'+password]); "
            "sys.exit(result.returncode)")
    run('--entrypoint','python3','calibre-web','-c',code,
        input=required('CALIBRE_PASSWORD')+'\n')
    with sqlite3.connect(db) as connection:
        connection.execute('UPDATE user SET name=? WHERE name=?', (required('ADMIN_USER'),'admin'))
        # Supported settings in upstream 0.6.27, the digest-pinned version.
        connection.execute("UPDATE settings SET config_calibre_dir='/library', config_calibre_split=1, config_calibre_split_dir='/books'")
    for path in [base,*base.rglob('*')]:
        os.chown(path, int(required('PUID')), int(required('PGID')))
    pending.unlink(missing_ok=True)
    (base/'.bootstrap-complete').touch(mode=0o600)
if not Path('/srv/docker/appdata/calibre-web/library/metadata.db').is_file():
    print('WARNING: Calibre-Web needs a valid Calibre metadata.db in the NVMe library directory; see docs/APPS-UTILITIES.md.')
