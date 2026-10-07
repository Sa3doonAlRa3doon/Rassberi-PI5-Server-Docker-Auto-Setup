#!/usr/bin/env python3
"""Retry selected applications whose verified storage was absent at boot."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = Path('/srv/docker')
PENDING = BASE / 'configs/storage-start-pending.json'
LOCK = Path('/run/lock/pi-server.lock')

sys.path.insert(0, str(BASE / 'scripts'))
import app_selection


def read_list(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


def write_pending(values):
    values = sorted(set(values))
    if not values:
        try:
            PENDING.unlink()
        except FileNotFoundError:
            pass
        return
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    temporary = PENDING.with_name('.' + PENDING.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as handle:
        json.dump(values, handle, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, PENDING)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    if os.geteuid() != 0:
        raise RuntimeError('storage-resume.py must run as root')
    lock = LOCK.open('a')
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        manifest = json.loads((BASE / 'manifest.json').read_text(encoding='utf-8'))
        known = {app['name']: app for app in manifest}
        installed = set(app_selection.installed_names(BASE, manifest))
        desired = set(app_selection.startup_names(BASE, manifest)) & installed
        pending = set(read_list(PENDING)) & desired & set(known)
        holds = set(read_list(BASE / 'configs/storage-review-required.json'))
        pending -= holds
        write_pending(pending)
        if not pending:
            return 0

        guard = load_module('pi_storage_guard_resume', BASE / 'scripts/storage_guard.py')
        config = BASE / 'configs/storage.json'
        report = BASE / 'logs' / 'storage-resume.log'
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open('a', encoding='utf-8') as log:
            try:
                guard.check(required=['root'], manifest=[], config=config)
            except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                log.write(f'DELAYED root storage unavailable: {exc}\n')
                return 0
            boot = load_module('pi_boot_storage_resume', BASE / 'scripts/boot-storage.py')
            for app in boot.startup_order(manifest, pending):
                definition = known[app]
                try:
                    guard.check(required=guard.app_requirements(definition, config), manifest=[definition],
                                require_dirs=True, config=config)
                except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                    log.write(f'DELAYED storage unavailable: {app}: {exc}\n')
                    continue
                result = subprocess.run([sys.executable, str(BASE / 'scripts/manage.py'), 'start', app,
                                         '--report-dir', str(BASE / 'logs' / 'resume')],
                                        stdout=log, stderr=log)
                pending.discard(app)
                if result.returncode == 0:
                    log.write(f'RESUMED after storage return: {app}\n')
                else:
                    log.write(f'REVIEW required after storage return: {app} rc={result.returncode}\n')
                write_pending(pending)
            write_pending(pending)
        return 0
    finally:
        lock.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('ERROR: storage resume: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
