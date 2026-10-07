#!/usr/bin/env python3
"""Apply the reviewed storage migration to an existing Pi without reinstalling apps."""
import argparse
import ast
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import time

BASE = Path('/srv/docker')
PACKAGE = Path(__file__).resolve().parents[1]
ROOT_RUNTIME_DIRS = {
    'appdata/storage-metrics': (1000, 1000, 0o750),
    'appdata/filebrowser/root': (None, None, 0o750),
}


def load_host_module():
    spec = importlib.util.spec_from_file_location('pi_host_setup', PACKAGE / 'scripts/host-setup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def read_array(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, list) or any(not isinstance(x, str) for x in data):
        raise RuntimeError('Expected an application-name JSON array: ' + str(path))
    return data


def safe_relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '\\' in value or not path.parts:
        raise RuntimeError('Unsafe migration path: ' + value)
    if path.parts[0] in {'appdata', 'databases', 'backups', 'logs'} or path.name == '.env' or path.name == 'server.env':
        raise RuntimeError('Migration must never replace persistent data/secrets: ' + value)
    if path.name in {'storage-autostart.json', 'storage-review-required.json', 'enabled-apps.txt'}:
        raise RuntimeError('Runtime selections must be preserved separately: ' + value)
    return Path(*path.parts)


def plan_project(host, records):
    changes, expected = {}, {}
    for item in records:
        if str(item['path']).startswith('/'):
            continue
        relative = safe_relative(item['path'])
        source, target = PACKAGE / relative, BASE / relative
        if source.resolve() != source.absolute() or target.resolve() != target.absolute():
            raise RuntimeError('Symlinked migration path requires manual review: ' + str(relative))
        content = source.read_bytes()
        if host.digest(content) != item['after_sha256']:
            raise RuntimeError('Package hash mismatch: ' + str(relative))
        old = target.read_bytes() if target.exists() else None
        prior = host.digest(old) if old is not None else None
        if prior not in {item.get('before_sha256'), item['after_sha256']}:
            raise RuntimeError('Customized/unknown deployed file preserved; manually review: ' + str(target))
        expected[str(target)] = old
        if old != content:
            changes[str(target)] = content
    return changes, expected


def inspect_containers():
    ids = command(['docker', 'ps', '-aq'], capture_output=True, text=True).stdout.split()
    return json.loads(command(['docker', 'inspect', *ids], capture_output=True, text=True).stdout) if ids else []


def storage_dependencies(app):
    paths = [d['path'] for d in app.get('directories', [])]
    return any(path.startswith(('/mnt/hdd/', '/mnt/media/')) or path in ('/mnt/hdd', '/mnt/media') for path in paths) or bool(app.get('mounts'))


def bound_storage(container):
    return any(m.get('Source', '').startswith(('/mnt/hdd/', '/mnt/media/')) or m.get('Source') in ('/mnt/hdd', '/mnt/media') for m in container.get('Mounts', []))


def data_review_reason(app):
    paths = [Path(d['path']) for d in app.get('directories', []) if d['path'].startswith(('/mnt/hdd/', '/mnt/media/'))]
    missing = [str(path) for path in paths if not path.is_dir()]
    if missing:
        return 'Required data directories are missing: ' + ', '.join(missing)
    if paths and all(not any(path.iterdir()) for path in paths):
        return 'All declared data directories are empty; verify files were recovered from the retired HDD before enabling this app.'
    if app['name'] == 'nextcloud':
        config = BASE / 'appdata/nextcloud/html/config/config.php'
        root = Path('/mnt/hdd/Nextcloud')
        if config.exists() and not any((root / name).exists() for name in ('.ocdata', '.ncdata')):
            return 'Initialized Nextcloud configuration exists but the data-directory marker is absent on the replacement HDD.'
    return None


def guard(app=None, write_test=False):
    args = ['python3', str(PACKAGE / 'scripts/storage_guard.py'), '--config', str(PACKAGE / 'configs/storage.json'),
            '--manifest', str(PACKAGE / 'manifest.json')]
    args += ['--app', app, '--directories'] if app else ['--only', 'root', 'hdd']
    if write_test:
        args.append('--write-test')
    command(args)


def runtime_directories(dry_run):
    """Create only the two new, empty NVMe scaffolds needed by this release."""
    missing = []
    for relative, (uid, gid, mode) in ROOT_RUNTIME_DIRS.items():
        if uid is None or gid is None:
            uid = gid = 1000
            envfile = BASE / 'compose/filebrowser/.env'
            if envfile.is_symlink():
                raise RuntimeError('Refusing symlinked File Browser .env while creating its NVMe scaffold')
            if envfile.is_file():
                values = {}
                for line in envfile.read_text().splitlines():
                    if '=' in line and not line.lstrip().startswith('#'):
                        key, value = line.split('=', 1)
                        values[key.strip()] = value.strip()
                try:
                    uid = int(values.get('PUID', uid))
                    gid = int(values.get('PGID', gid))
                except ValueError:
                    raise RuntimeError('File Browser PUID/PGID in .env must be numeric')
        path = BASE / relative
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise RuntimeError('Required NVMe runtime path is not a real directory: ' + str(path))
        if not path.exists():
            missing.append(str(path))
            if not dry_run:
                path.mkdir(parents=True, mode=mode, exist_ok=True)
                os.chown(path, uid, gid)
                path.chmod(mode)
    return missing


def syntax_check(changes):
    with tempfile.TemporaryDirectory(prefix='pi-storage-validate-') as tmp:
        folder = Path(tmp)
        for absolute, content in changes.items():
            path = Path(absolute)
            if path.suffix == '.py':
                ast.parse(content.decode(), filename=absolute)
            elif path.suffix == '.json':
                json.loads(content)
            elif path.suffix == '.sh':
                candidate = folder / path.name
                candidate.write_bytes(content)
                command(['bash', '-n', str(candidate)])
            if path.name == 'compose.yml':
                app = path.parent.name
                candidate = folder / app / 'compose.yml'
                candidate.parent.mkdir()
                candidate.write_bytes(content)
                env = BASE / 'compose' / app / '.env'
                if not env.is_file():
                    raise RuntimeError('Existing application .env missing; recover it before updating: ' + app)
                command(['docker', 'compose', '--project-name', 'pi-' + app, '--project-directory',
                         str(BASE / 'compose' / app), '--env-file', str(env), '-f', str(candidate), 'config', '--quiet'],
                        stdout=subprocess.DEVNULL)


def validate_host():
    """This legacy supplied-Pi migration also requires the supported host family."""
    command([sys.executable, str(PACKAGE / 'scripts/platform_check.py')])
    state = command(['systemctl', 'show', 'docker.service', '--property=LoadState', '--value'],
                    capture_output=True, text=True).stdout.strip()
    if state != 'loaded':
        raise RuntimeError('A systemd-managed docker.service is required for storage migration.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Validate and show plans; leave server files and containers unchanged.')
    args = parser.parse_args()
    if os.name != 'posix' or os.geteuid() != 0:
        raise RuntimeError('Run on a supported Linux ARM64 host with sudo, not on Windows.')
    validate_host()
    os.umask(0o077)
    import fcntl
    lock = open('/run/lock/pi-server.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if not (BASE / 'manifest.json').is_file():
        raise RuntimeError('Existing /srv/docker deployment not found; use install-all.sh for a new deployment.')
    if PACKAGE == BASE:
        raise RuntimeError('Run the updated package from ~/Downloads, separate from the live /srv/docker deployment.')
    host = load_host_module()
    raw = json.loads((PACKAGE / 'migration-files.json').read_text())
    records = raw['files'] if isinstance(raw, dict) else raw
    extra_host = raw.get('host_files', []) if isinstance(raw, dict) else [r for r in raw if str(r['path']).startswith('/')]
    changes, expected = plan_project(host, records)
    allowed_host = {}
    by_path = {r['path']: r for r in records}
    for target, source in host.managed_files(PACKAGE).items():
        old = by_path.get(source, {}).get('before_sha256')
        allowed_host[target] = {old} if old else set()
    for item in extra_host:
        if item['path'] not in host.managed_files(PACKAGE):
            raise RuntimeError('Unexpected host migration destination: ' + item['path'])
        if item.get('before_sha256'):
            allowed_host[item['path']].add(item['before_sha256'])
    host_changes = host.plan_host_files(PACKAGE, allowed_host)
    # Refuse custom files and invalid syntax before changing a single container.
    command(['docker', 'info'], stdout=subprocess.DEVNULL)
    guard(write_test=not args.dry_run)
    storage = json.loads((PACKAGE / 'configs/storage.json').read_text())
    fstab = Path('/etc/fstab').read_bytes()
    candidate = host.fstab_candidate(fstab.decode(), storage)
    host.validate_fstab(candidate)
    host_changes['/etc/fstab'] = candidate.encode()
    for name, data in host_changes.items():
        target = Path(name)
        expected[name] = target.read_bytes() if target.exists() else None
        if expected[name] != data:
            changes[name] = data
    syntax_check(changes)
    manifest = json.loads((PACKAGE / 'manifest.json').read_text())
    dependent = {a['name']: a for a in manifest if storage_dependencies(a)}
    inventory = inspect_containers()
    for container in inventory:
        project = container['Config'].get('Labels', {}).get('com.docker.compose.project', '')
        if bound_storage(container):
            if not project.startswith('pi-') or project[3:] not in {a['name'] for a in manifest}:
                raise RuntimeError('Unmanaged storage-dependent container needs explicit review: ' + container['Name'])
            dependent.setdefault(project[3:], next(a for a in manifest if a['name'] == project[3:]))
    affected = [c for c in inventory if c['Config'].get('Labels', {}).get('com.docker.compose.project', '').removeprefix('pi-') in dependent]
    if any(c['State']['Status'] == 'paused' for c in affected):
        raise RuntimeError('Unpause the affected containers before applying the storage migration.')
    original = [c for c in affected if c['State']['Status'] in ('running', 'restarting')]
    original_apps = {c['Config']['Labels']['com.docker.compose.project'][3:] for c in original}
    reasons = {name: reason for name, app in dependent.items() if (reason := data_review_reason(app))}
    prior_hold = set(read_array(BASE / 'configs/storage-review-required.json'))
    hold = prior_hold | set(reasons)
    desired_file = BASE / 'configs/storage-autostart.json'
    desired = read_array(desired_file) if desired_file.exists() else sorted(original_apps - hold)
    root_dirs = runtime_directories(True)
    plan = {'mode': 'dry-run' if args.dry_run else 'apply', 'files': sorted(changes),
            'affected_containers': [{'id': c['Id'], 'name': c['Name'], 'status': c['State']['Status'],
                'restart': c['HostConfig'].get('RestartPolicy', {})} for c in affected],
            'original_running_apps': sorted(original_apps), 'review_required': reasons,
            'storage_autostart': desired, 'data_directories_created': root_dirs,
            'note': 'No data is moved. Missing/empty data needs review; no OS/media fstab entries change.'}
    print(json.dumps(plan, indent=2))
    if args.dry_run:
        print('DRY RUN PASSED: no live files, restart policies or containers changed.')
        return 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_dir = BASE / 'backups' / ('storage-update-' + stamp)
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = backup_dir / 'migration-report.json'
    host.atomic_write(report, json.dumps(plan, indent=2).encode() + b'\n', mode=0o600)
    try:
        # Recheck all reviewed bytes immediately before applying; never overwrite a concurrent edit.
        for name, previous in expected.items():
            path = Path(name)
            actual = path.read_bytes() if path.exists() else None
            if actual != previous:
                raise RuntimeError('File changed after preflight; nothing further will be written: ' + name)
        runtime_directories(False)
        # Disable legacy daemon-boot restarts BEFORE replacing the old global Docker gate.
        for container in affected:
            command(['docker', 'update', '--restart=no', container['Id']], stdout=subprocess.DEVNULL)
        for container in original:
            command(['docker', 'stop', '--time', '120', container['Id']], stdout=subprocess.DEVNULL)
        for name, data in changes.items():
            if name.startswith('/etc/'):
                continue
            mode = 0o755 if Path(name).suffix in ('.sh', '.py') else 0o644
            host.atomic_write(name, data, backup_dir, mode=mode)
        host.atomic_write(BASE / 'configs/storage-review-required.json', json.dumps(sorted(hold)).encode() + b'\n', backup_dir, mode=0o600)
        if not desired_file.exists():
            host.atomic_write(desired_file, json.dumps(desired).encode() + b'\n', mode=0o600)
        for name, data in changes.items():
            if name.startswith('/etc/'):
                host.atomic_write(name, data, backup_dir)
        command(['systemctl', 'daemon-reload'])
        command(['systemctl', 'enable', 'pi-storage-start.service', 'pi-storage-watch.timer',
                 'pi-storage-resume.timer'])
        # No Docker restart and no --now: the guarded boot job takes the same lock.
        for container in affected:
            command(['docker', 'update', '--restart=on-failure:5', container['Id']], stdout=subprocess.DEVNULL)
        for name in sorted(original_apps):
            if name in hold:
                print('WARNING: left stopped pending data review: ' + name + ': ' + reasons.get(name, 'existing hold'))
                continue
            guard(app=name, write_test=True)
            group = [c for c in original if c['Config']['Labels']['com.docker.compose.project'] == 'pi-' + name]
            group.sort(key=lambda c: c['Config']['Labels'].get('com.docker.compose.service') not in ('db', 'redis'))
            for container in group:
                command(['docker', 'start', container['Id']], stdout=subprocess.DEVNULL)
                if container['Config']['Labels'].get('com.docker.compose.service') in ('db', 'redis'):
                    for attempt in range(120):
                        status = command(['docker', 'inspect', '--format', '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}', container['Id']], capture_output=True, text=True).stdout.strip()
                        if status in ('healthy', 'running'):
                            break
                        time.sleep(2)
                    else:
                        raise RuntimeError('Backend failed to become ready: ' + container['Name'])
        plan['result'] = 'COMPLETED WITH DATA REVIEW WARNINGS' if hold else 'SUCCESS'
        plan['review_holds'] = sorted(hold)
        host.atomic_write(report, json.dumps(plan, indent=2).encode() + b'\n', mode=0o600)
        print(plan['result'] + '; report and preserved configurations: ' + str(backup_dir))
        return 0
    except Exception as exc:
        plan['result'] = 'FAILED'
        plan['error'] = str(exc)
        host.atomic_write(report, json.dumps(plan, indent=2).encode() + b'\n', mode=0o600)
        print('FAILED: affected containers may remain stopped with restart disabled. Preserved configurations and original states: ' + str(backup_dir), file=sys.stderr)
        raise


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('ERROR: storage migration stopped: ' + str(exc), file=sys.stderr)
        sys.exit(1)
