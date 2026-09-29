#!/usr/bin/env python3
"""Stage a reviewed package expansion without replacing private/runtime state."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
TARGET = Path('/srv/docker')
RELEASE_FILE = 'RELEASE.json'
RELEASE_CODE = 'FIXED AND IMPROVED'
PROTECTED = {
    'configs/storage.json', 'configs/layout.json', 'configs/portable-backup.json',
    'configs/storage-autostart.json', 'configs/storage-review-required.json',
    'configs/storage-paused.json', 'enabled-apps.txt', 'server.env',
}
RUNTIME_PARTS = {'appdata', 'databases', 'backups', 'logs', '__pycache__', '.git'}


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        while block := handle.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def atomic(path, content, mode):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path.absolute():
        raise RuntimeError('Symlinked managed target: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_release(path):
    path = Path(path)
    if not path.is_file():
        return None
    release = json.loads(path.read_text())
    if (not isinstance(release, dict) or release.get('release_code') != RELEASE_CODE or
            release.get('state') != 'published' or
            not isinstance(release.get('release_id'), int) or release['release_id'] < 1):
        raise RuntimeError('Invalid release marker; expected a published FIXED AND IMPROVED package')
    return release


def release_gate():
    """Allow only a published package newer than the installed release."""
    incoming = read_release(SOURCE / RELEASE_FILE)
    if incoming is None:
        raise RuntimeError('Package has no RELEASE.json; code updates require a published release')
    installed = read_release(TARGET / RELEASE_FILE)
    if installed and incoming['release_id'] <= installed['release_id']:
        raise RuntimeError(
            f"No newer published release: installed {installed['release_id']}, "
            f"package {incoming['release_id']}. Increment release_id only when the package is fixed and ready."
        )
    return incoming, installed


def deployed_replacements():
    path = TARGET / 'configs/layout.json'
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    placements = data.get('placements', {})
    if not isinstance(placements, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in placements.items()):
        raise RuntimeError('Invalid deployed storage layout; review before upgrade')
    return placements


def prepared_source():
    temporary = tempfile.TemporaryDirectory(prefix='pi-release-')
    stage = Path(temporary.name) / 'package'
    shutil.copytree(SOURCE, stage, ignore=shutil.ignore_patterns('logs', '__pycache__', '.git'))
    replacements = deployed_replacements()
    if replacements:
        setup = load_module('release_storage_setup', stage / 'scripts/storage_setup.py')
        files = setup.render_files(stage, replacements)
        for path, content in files.items():
            path.write_bytes(content)
        manifest = json.loads((stage / 'manifest.json').read_text())
        config_path = TARGET / 'configs/storage.json'
        config = json.loads(config_path.read_text())
        for app in manifest:
            for item in app.get('directories', []):
                item['path'] = setup.mapped_path(item['path'], replacements)
            database = app.get('database') or {}
            if database.get('path'):
                database['path'] = setup.mapped_path(database['path'], replacements)
        guard = load_module('release_storage_guard', stage / 'scripts/storage_guard.py')
        for app in manifest:
            app['mounts'] = [key for key in guard.app_requirements(app, config) if key != 'root']
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return temporary, stage


def files(stage):
    for path in stage.rglob('*'):
        if not path.is_file() or path.name == 'release-index.json':
            continue
        rel = path.relative_to(stage).as_posix()
        if set(path.relative_to(stage).parts) & RUNTIME_PARTS or rel in PROTECTED or path.name == '.env':
            continue
        yield rel, path


def plan(stage, index):
    changes, preserved = [], []
    for rel, source in files(stage):
        destination = TARGET / Path(rel)
        current = sha256(destination) if destination.is_file() else None
        after = sha256(source)
        if rel == RELEASE_FILE and current is not None:
            installed = read_release(destination)
            incoming = read_release(source)
            if installed and incoming['release_id'] > installed['release_id']:
                changes.append({'path': rel, 'action': 'replace', 'before': current, 'after': after})
            else:
                preserved.append({'path': rel, 'reason': 'release marker is not newer',
                                  'current': current, 'incoming': after})
            continue
        previous = (index.get(rel) or {}).get('previous_sha256')
        if current == after:
            continue
        if current is None or current == previous:
            changes.append({'path': rel, 'action': 'add' if current is None else 'replace',
                            'before': current, 'after': after})
        else:
            preserved.append({'path': rel, 'reason': 'locally changed or from an unknown release',
                              'current': current, 'incoming': after})
    return changes, preserved


def host_units(stage, index):
    result = []
    names = [path.name for path in (stage / 'systemd').iterdir() if path.is_file()]
    for name in names:
        destination = Path('/etc/systemd/system') / name
        source = stage / 'systemd' / name
        rel = 'systemd/' + name
        current = sha256(destination) if destination.is_file() else None
        after = sha256(source)
        previous = (index.get(rel) or {}).get('previous_sha256')
        if current == after:
            continue
        if current is None or current == previous:
            result.append((destination, source, current))
        else:
            raise RuntimeError('Customized systemd unit needs review before upgrade: ' + str(destination))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply the exact dry-run plan')
    parser.add_argument('--dry-run', action='store_true', help='Explicit read-only mode (the default)')
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise RuntimeError('Choose --dry-run or --apply')
    if os.geteuid() != 0 or os.name != 'posix':
        raise RuntimeError('Run with sudo on the Raspberry Pi')
    if SOURCE == TARGET or not (TARGET / 'manifest.json').is_file():
        raise RuntimeError('Run this from the new downloaded package against an existing /srv/docker installation')
    if SOURCE.is_symlink() or TARGET.is_symlink():
        raise RuntimeError('Source and installed package must not be symlinks')
    incoming_release, installed_release = release_gate()
    subprocess.run(['python3', str(TARGET / 'scripts/storage_guard.py'), '--only', 'root'], check=True)
    index = json.loads((SOURCE / 'release-index.json').read_text())['files']
    temporary, stage = prepared_source()
    try:
        changes, preserved = plan(stage, index)
        units = host_units(stage, index)
        report = {'mode': 'apply' if args.apply else 'dry-run', 'changes': changes,
                  'preserved_local_files': preserved,
                  'systemd_changes': [str(row[0]) for row in units],
                  'release_id': incoming_release['release_id'],
                  'release_code': incoming_release['release_code'],
                  'previous_release_id': installed_release['release_id'] if installed_release else None,
                  'private_state_preserved': sorted(PROTECTED),
                  'next': 'After apply: sudo /srv/docker/install-all.sh'}
        print(json.dumps(report, indent=2))
        if not args.apply:
            return 0
        import fcntl
        lock = open('/run/lock/pi-server.lock', 'a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Recompute under the lock so dry-run information cannot become a stale apply.
        fresh, fresh_preserved = plan(stage, index)
        if fresh != changes or fresh_preserved != preserved:
            raise RuntimeError('Installed files changed after planning; rerun dry-run')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = TARGET / 'backups' / ('package-upgrade-' + stamp)
        backup.mkdir(parents=True, mode=0o700)
        changed = {item['path'] for item in changes}
        for rel in changed:
            destination = TARGET / Path(rel)
            if destination.exists():
                saved = backup / Path(rel)
                saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(destination, saved)
        for destination, _, current in units:
            if current:
                saved = backup / 'host-units' / destination.name
                saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(destination, saved)
        for rel, source in files(stage):
            if rel not in changed:
                continue
            mode = 0o755 if source.suffix in {'.py', '.sh'} or source.name.endswith('.sh') else 0o644
            atomic(TARGET / Path(rel), source.read_bytes(), mode)
        for destination, source, _ in units:
            atomic(destination, source.read_bytes(), 0o644)
        atomic(backup / 'report.json', (json.dumps(report, indent=2) + '\n').encode(), 0o600)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', 'pi-storage-start.service',
                        'pi-storage-watch.timer', 'pi-storage-metrics.timer'], check=True)
        print('STAGED: package files upgraded; secrets, enabled-apps, storage identity and data were preserved.')
        print('NEXT: sudo /srv/docker/install-all.sh')
        return 0
    finally:
        temporary.cleanup()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError, BlockingIOError) as exc:
        print('ERROR: ' + str(exc), file=__import__('sys').stderr)
        raise SystemExit(1)
