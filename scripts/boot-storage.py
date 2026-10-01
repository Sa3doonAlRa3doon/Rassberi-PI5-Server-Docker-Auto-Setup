#!/usr/bin/env python3
"""Start configured Compose applications after Docker, with per-drive guards."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys

BASE = Path('/srv/docker')
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(BASE / 'scripts'))
import app_selection


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


def startup_order(manifest, selected):
    """Order selected apps by boot priority without starting a dependent first."""
    by_name = {app['name']: app for app in manifest}
    remaining = {name for name in selected if name in by_name}
    ordered = []
    effective_priority = {
        name: by_name[name].get('boot_priority', 1000) for name in remaining
    }

    # A dependency inherits the earliest priority of anything that needs it.
    # That lets a prioritized application and its selected prerequisites start
    # ahead of unrelated default-priority applications.
    changed = True
    while changed:
        changed = False
        for name in remaining:
            for dependency in set(by_name[name].get('requires', [])) & remaining:
                if effective_priority[dependency] > effective_priority[name]:
                    effective_priority[dependency] = effective_priority[name]
                    changed = True

    def priority(name):
        app = by_name[name]
        # Apps without an explicit priority retain their established manifest order.
        return (effective_priority[name], app.get('order', 50), name)

    while remaining:
        ready = [name for name in remaining
                 if not (set(by_name[name].get('requires', [])) & remaining)]
        if not ready:
            raise RuntimeError('Startup dependency cycle: ' + ', '.join(sorted(remaining)))
        name = min(ready, key=priority)
        ordered.append(name)
        remaining.remove(name)
    return ordered


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
    installed = set(app_selection.installed_names(BASE, manifest))
    desired = set(app_selection.startup_names(BASE, manifest)) & installed
    # enabled-apps.txt is the explicit current startup selection.
    holds = set(names(BASE / 'configs/storage-review-required.json'))
    report = BASE / 'logs' / 'boot-storage.log'
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open('a', encoding='utf-8') as log:
        for app in startup_order(manifest, desired):
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
