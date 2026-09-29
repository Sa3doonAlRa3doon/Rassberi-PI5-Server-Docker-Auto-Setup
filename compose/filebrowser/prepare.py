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
base = Path('/srv/docker/appdata/filebrowser/database')
if not (base/'filebrowser.db').exists():
    # A temporary DB makes an interrupted initialization safely retryable.
    initial = base/'bootstrap.db'
    if initial.exists():
        raise RuntimeError('Incomplete File Browser bootstrap.db exists. Preserve it for diagnosis; move it aside after inspection and rerun.')
    run('--entrypoint','/bin/filebrowser','filebrowser','-d','/database/bootstrap.db',
        'config','init','--root','/srv','--address','0.0.0.0','--port','80')
    run('--entrypoint','/bin/sh','filebrowser','-c',
        'IFS= read -r password; exec /bin/filebrowser -d /database/bootstrap.db users add "$1" "$password" --perm.admin',
        'bootstrap',required('ADMIN_USER'),input=required('FILEBROWSER_PASSWORD')+'\n')
    initial.replace(base/'filebrowser.db')
