#!/usr/bin/env python3
"""Start configured Compose applications after Docker, with per-drive guards."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BASE = Path('/srv/docker')
PENDING = BASE / 'configs/storage-start-pending.json'
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


def pending_names(path=PENDING, desired=None):
    """Read the guarded startup queue, keeping only currently selected apps."""
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        value = []
    if not isinstance(value, list):
        value = []
    result = {item for item in value if isinstance(item, str) and item}
    return result if desired is None else result & set(desired)


def write_pending(path, values):
    """Atomically persist or remove the root-only startup queue."""
    path = Path(path)
    values = sorted({item for item in values if isinstance(item, str) and item})
    if not values:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(values, handle, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_guard():
    spec = importlib.util.spec_from_file_location('pi_storage_guard_boot', BASE / 'scripts/storage_guard.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    return guard


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
    pending = pending_names(PENDING, desired)
    write_pending(PENDING, pending)
    guard_module = load_guard()
    storage_config = BASE / 'configs/storage.json'
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
                pending.discard(app)
                write_pending(PENDING, pending)
                continue
            app_definition = next(item for item in manifest if item['name'] == app)
            try:
                guard_module.check(required=guard_module.app_requirements(app_definition, storage_config),
                                   manifest=[app_definition], require_dirs=True,
                                   config=storage_config)
            except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                pending.add(app)
                write_pending(PENDING, pending)
                log.write(f'PENDING storage unavailable: {app}: {exc}\n')
                continue
            result = subprocess.run([sys.executable, str(BASE / 'scripts/manage.py'), 'start', app,
                                     '--report-dir', str(BASE / 'logs' / 'boot')],
                                    stdout=log, stderr=log)
            if result.returncode == 0:
                pending.discard(app)
                log.write('STARTED ' + app + ' rc=0\n')
            else:
                pending.add(app)
                log.write('SKIPPED/FAILED; left pending for one guarded retry ' + app +
                          ' rc=' + str(result.returncode) + '\n')
            write_pending(PENDING, pending)
        write_pending(PENDING, pending)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print('ERROR: boot storage start: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
