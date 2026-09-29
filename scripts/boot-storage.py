#!/usr/bin/env python3
"""Start configured Compose applications after Docker, with per-drive guards."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys

BASE = Path('/srv/docker')


def names(path):
    if not path.is_file():
        return []
    if path.suffix == '.json':
        try:
            value = json.loads(path.read_text())
            return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []
        except (OSError, ValueError):
            return []
    return [line.strip() for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def main():
    if __import__('os').geteuid() != 0:
        raise RuntimeError('boot-storage.py must run as root')
    guard = [sys.executable, str(BASE / 'scripts/storage_guard.py'),
             '--only', 'root', '--config', str(BASE / 'configs/storage.json'),
             '--manifest', str(BASE / 'manifest.json')]
    subprocess.run(guard, check=True)
    lock = open('/run/lock/pi-server.lock', 'a')
    # systemd bounds this service's wait; serialize with backup/install/migration.
    fcntl.flock(lock, fcntl.LOCK_EX)
    manifest = json.loads((BASE / 'manifest.json').read_text())
    known = {app['name'] for app in manifest}
    desired = set(names(BASE / 'enabled-apps.txt'))
    # enabled-apps.txt is the explicit current startup selection.
    holds = set(names(BASE / 'configs/storage-review-required.json'))
    report = BASE / 'logs' / 'boot-storage.log'
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open('a', encoding='utf-8') as log:
        for app in sorted(desired, key=lambda item: next((a.get('order', 50) for a in manifest if a['name'] == item), 999)):
            if app not in known:
                log.write('SKIP unknown application: ' + app + '\n')
                continue
            if app in holds:
                log.write('SKIP review hold: ' + app + '\n')
                continue
            result = subprocess.run([sys.executable, str(BASE / 'scripts/manage.py'), 'start', app,
                                     '--report-dir', str(BASE / 'logs' / 'boot')],
                                    stdout=log, stderr=log)
            log.write(('STARTED ' if result.returncode == 0 else 'SKIPPED/FAILED ') + app +
                      ' rc=' + str(result.returncode) + '\n')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print('ERROR: boot storage start: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
