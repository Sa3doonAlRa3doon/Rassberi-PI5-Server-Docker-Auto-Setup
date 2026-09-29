#!/usr/bin/env python3
"""Preserve the hub key; publish only its public half to the local agent."""
import os
from pathlib import Path
import subprocess
import sys

BASE = Path('/srv/docker')
sys.path.insert(0, str(BASE/'scripts'))
from monitoring_devices import configure
import storage_guard


def main():
    storage_guard.check(required=['root'])
    key = BASE/'appdata/beszel/id_ed25519'
    if key.is_symlink():
        raise RuntimeError('Refusing a symlinked Beszel key')
    if not key.exists():
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)], check=True)
    key.chmod(0o600)
    public = subprocess.check_output(['ssh-keygen','-y','-f',str(key)],text=True)
    target = BASE/'configs/beszel/hub-key.pub'
    if target.is_symlink():
        raise RuntimeError('Refusing a symlinked public-key file')
    target.write_text(public,encoding='utf-8')
    target.chmod(0o644)
    configure('beszel')


if __name__ == '__main__':
    main()
