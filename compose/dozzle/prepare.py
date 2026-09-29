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
path = Path('/srv/docker/appdata/dozzle/users.yml')
if not path.exists():
    content = run('dozzle','generate', required('ADMIN_USER'), '--user-roles','download',
                  input=required('DOZZLE_PASSWORD')+'\n', capture=True)
    if not content or 'users:' not in content:
        raise RuntimeError('Dozzle did not return a users.yml configuration.')
    temp = path.with_name('users.yml.bootstrap')
    with temp.open('w') as stream: stream.write(content)
    temp.chmod(0o600)
    temp.replace(path)
