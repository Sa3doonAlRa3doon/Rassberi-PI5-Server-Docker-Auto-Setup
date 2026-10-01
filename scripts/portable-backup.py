#!/usr/bin/env python3
"""Portable, versioned file snapshots and guarded recovery into empty staging space.

Plan does not write or stop anything. Create never deletes earlier snapshots.
Verify and staging restore work without the original Pi installation.
"""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import time

BASE = Path('/srv/docker')
DEFAULT = {'mount': '/mnt/backup', 'uuid': '', 'folder': 'pi-server', 'include_bulk': True, 'reserve_gib': 5}
FORMAT = 'pi-readable-backup-v1'
BUFFER = 4 * 1024 * 1024


def run(args, **kwargs):
    return subprocess.run(args, check=True, timeout=kwargs.pop('timeout', 120), **kwargs)


def output(args):
    return run(args, capture_output=True, text=True).stdout


def require_root():
    if os.name != 'posix' or os.geteuid() != 0:
        raise RuntimeError('Run this operation with sudo on Linux.')


@contextmanager
def server_lock():
    import fcntl
    with open('/run/lock/pi-server.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def relative_name(value):
    name = PurePosixPath(value)
    if not value or not name.parts or name.is_absolute() or '..' in name.parts or '\\' in value or '\x00' in value or str(name) != value:
        raise RuntimeError('Unsafe relative filename: ' + repr(value))
    return name


def no_symlink(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise RuntimeError('Path must be absolute and contain no symlinks: ' + str(path))
    return path


def load_config(path):
    config = {**DEFAULT, **(read_json(path) if Path(path).is_file() else {})}
    mount = PurePosixPath(config['mount'])
    if not mount.is_absolute() or mount.anchor != '/' or '..' in mount.parts or str(mount) != config['mount']:
        raise RuntimeError('Backup mount must be a normalized absolute Linux path.')
    if os.name == 'posix':
        no_symlink(config['mount'])
    if config['mount'] == '/':
        raise RuntimeError('Backup mount must be a separate disk, not /.')
    relative_name(config['folder'])
    if not isinstance(config['include_bulk'], bool):
        raise RuntimeError('include_bulk must be true or false.')
    if not isinstance(config['reserve_gib'], int) or not 1 <= config['reserve_gib'] <= 100:
        raise RuntimeError('reserve_gib must be an integer from 1 to 100.')
    if config['uuid'] and not re.fullmatch(r'[A-Fa-f0-9-]{4,64}', config['uuid']):
        raise RuntimeError('Invalid backup filesystem UUID.')
    return config


def exact_mount(path, uuid=None, writable=False):
    path = str(no_symlink(path))
    data = json.loads(output(['findmnt', '--json', '--mountpoint', path,
                              '--output', 'TARGET,SOURCE,UUID,FSTYPE,OPTIONS']))['filesystems']
    if len(data) != 1 or data[0]['target'] != path:
        raise RuntimeError('Not an exact mounted filesystem: ' + path)
    row = data[0]
    if uuid and row.get('uuid', '').lower() != uuid.lower():
        raise RuntimeError('Wrong filesystem UUID at ' + path)
    if writable and 'rw' not in row.get('options', '').split(','):
        raise RuntimeError('Read-only backup destination: ' + path)
    if not row.get('uuid'):
        raise RuntimeError('Filesystem has no stable UUID: ' + path)
    row['device_number'] = os.stat(path).st_dev
    return row


def physical_disks(source):
    device = source.split('[', 1)[0]
    if not device.startswith('/dev/'):
        raise RuntimeError('Cannot verify a physical disk for ' + source)
    tree = json.loads(output(['lsblk', '--json', '--paths', '--inverse', '--output', 'NAME,TYPE', device]))
    found = set()
    def visit(items):
        for item in items:
            if item.get('type') == 'disk':
                found.add(os.path.realpath(item['name']))
            visit(item.get('children', []))
    visit(tree.get('blockdevices', []))
    if not found:
        raise RuntimeError('Physical parent disk could not be determined: ' + source)
    return found


def storage_guard(base):
    spec = importlib.util.spec_from_file_location('portable_storage_guard', base / 'scripts/storage_guard.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    return guard


def device_map(config, guard):
    return guard.device_map(config) if hasattr(guard, 'device_map') else config


def saved_selection(base, manifest):
    """Read the install selection without making portable recovery depend on it.

    A package installed before app selection has no file and deliberately keeps
    the historic all-app behavior.  A saved selection is validated through the
    same helper used by the permanent settings panel.
    """
    base = Path(base)
    # Modern installations commit both installed and startup choices in one
    # atomic JSON file.  The legacy text file is only a compatibility copy and
    # may be absent after an interrupted compatibility refresh.
    if not ((base / 'installed-apps.txt').is_file() or
            (base / 'configs' / 'app-selection.json').is_file()):
        return {app['name'] for app in manifest}
    helper = base / 'scripts' / 'app_selection.py'
    if not helper.is_file():
        helper = Path(__file__).resolve().with_name('app_selection.py')
    spec = importlib.util.spec_from_file_location('portable_app_selection', helper)
    selection = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(selection)
    try:
        return set(selection.installed_names(base, manifest))
    except ValueError as error:
        raise RuntimeError('Saved application selection is invalid: ' + str(error)) from error


def configured_key(guard, config, devices, path):
    """Return the configured storage key for a path, or None when it is retired."""
    try:
        key = guard.path_key(str(path), config)
    except RuntimeError:
        return None
    return key if key in devices else None


def backup_manifest(base, manifest, config, guard):
    """Use current apps plus safe evidence of deselected historical app state.

    Old app data is retained when its config or a directory still exists on a
    storage device that remains in the user's current storage profile.  Paths
    from a retired device are never accessed through an unmounted mountpoint.
    """
    base = Path(base)
    devices = device_map(config, guard)
    selected = saved_selection(base, manifest)
    active = []
    historical = []
    unavailable = []
    for app in manifest:
        if app['name'] in selected:
            active.append(app)
            continue
        configured_directories = []
        retired_directories = []
        for item in app.get('directories', []):
            path = Path(item['path'])
            if configured_key(guard, config, devices, path) is None:
                retired_directories.append(str(path))
            elif path.is_dir():
                configured_directories.append(item)
        configured_env = (base / 'compose' / app['name'] / '.env').is_file()
        if configured_env or configured_directories:
            # Keep the original entry immutable.  Historical paths on retired
            # storage are omitted, while its remaining NVMe/config state stays
            # protected by the same database and container checks as active apps.
            historical_entry = {**app, 'directories': configured_directories}
            database = app.get('database') or {}
            database_path = database.get('path')
            # A historical compose environment is useful recovery evidence,
            # but its database cannot be included through an unconfigured
            # (possibly unplugged) path.  Keeping that database declaration
            # would make data_groups() add the retired path back into the plan.
            if database_path and configured_key(guard, config, devices, database_path) is None:
                historical_entry['database'] = None
                unavailable.append((app['name'], str(database_path)))
            active.append(historical_entry)
            historical.append(app['name'])
            if retired_directories:
                unavailable.extend((app['name'], path) for path in retired_directories)
    return active, sorted(selected), historical, unavailable


def data_groups(base, manifest):
    """Identify data by its original placement, even after an SSD/HDD migration."""
    layout = read_json(base / 'configs/layout.json') if (base / 'configs/layout.json').is_file() else {}
    reverse = sorted(((current, original) for original, current in layout.get('placements', {}).items()),
                     key=lambda pair: len(pair[0]), reverse=True)
    groups = {}
    for app in manifest:
        database = app.get('database') or {}
        sql = database.get('type') in {'postgres', 'mariadb'}
        db_path = database.get('path') if sql else None
        for item in app.get('directories', []):
            path = item['path']
            original = next((old + path[len(current):] for current, old in reverse
                             if path == current or path.startswith(current + '/')), path)
            if original == '/srv/docker/appdata/storage-metrics':
                continue  # Host timer continuously replaces this derived status file.
            if sql and (original.startswith('/srv/docker/databases/') or (db_path and
                    (path == db_path or path.startswith(db_path + '/')))):
                kind = 'database'
            elif original.startswith(('/srv/docker/appdata/', '/srv/docker/databases/')):
                kind = 'appdata'
            elif original.startswith(('/mnt/', '/media/')):
                kind = 'bulk'
            else:
                kind = 'control'
            groups[path] = {'path': path, 'original': original, 'kind': kind, 'app': app['name']}
        if db_path and sql:
            groups[db_path] = {'path': db_path, 'original': db_path, 'kind': 'database', 'app': app['name']}
    return list(groups.values())


def database_paths(base, manifest, app=None):
    return [Path(row['path']) for row in data_groups(base, manifest)
            if row['kind'] == 'database' and (app is None or row['app'] == app)]


def backup_storage_keys(groups, storage, guard):
    """Return only devices that contain selected or retained backup data.

    A storage profile can intentionally retain a disconnected, deselected
    device.  It must not make a backup fail, but every device used by an
    active or retained application remains a checked source even when bulk
    payloads are excluded from this snapshot.
    """
    devices = device_map(storage, guard)
    keys = {'root'}
    for row in groups:
        key = configured_key(guard, storage, devices, row['path'])
        if key is None:
            raise RuntimeError('Backup source is outside the configured storage profile: ' + str(row['path']))
        keys.add(key)
    return [key for key in devices if key in keys]


def validate_backup_groups(groups):
    """Fail closed if selected/retained state has disappeared since setup."""
    for row in groups:
        path = no_symlink(row['path'])
        if not path.is_dir():
            raise RuntimeError('Required selected or retained backup directory is missing: ' + str(path))


def source_list(base, manifest, devices, bulk, groups=None):
    roots = []
    for name in ['configs', 'compose', 'scripts', 'docs', 'systemd']:
        if (base / name).exists():
            roots.append(base / name)
    roots += [p for p in base.iterdir() if p.is_file() and not p.is_symlink()]
    # Select registered data groups, never an entire user drive. App state on an
    # external SSD is still required when bulk documents/media are excluded.
    for row in groups if groups is not None else data_groups(base, manifest):
        path = Path(row['path'])
        if row['kind'] == 'database' or (row['kind'] == 'bulk' and not bulk):
            continue
        # The plan must never call a snapshot successful while skipping an
        # application directory that was selected for backup.
        if not path.is_dir():
            raise RuntimeError('Required selected or retained backup directory is missing: ' + str(path))
        roots.append(path)
    unique = []
    for path in sorted(set(roots), key=lambda p: (len(p.parts), str(p))):
        no_symlink(path)
        if not any(parent == path or parent in path.parents for parent in unique):
            unique.append(path)
    for raw in database_paths(base, manifest):
        if any(root == raw or root in raw.parents for root in unique):
            raise RuntimeError('Raw SQL database overlaps a file-backup source; separate these data groups: ' + str(raw))
    return unique


def walk_source(path, expected_device):
    """Do not cross nested mounts or traverse links; record links as metadata."""
    details = path.lstat()
    if details.st_dev != expected_device:
        raise RuntimeError('Unexpected submount at ' + str(path))
    yield path, details
    if stat.S_ISDIR(details.st_mode):
        for child in sorted(path.iterdir()):
            if child.name == 'lost+found' and path.parent == Path('/mnt'):
                continue
            yield from walk_source(child, expected_device)


def make_plan(config, base=BASE):
    plan = {'ready': False, 'config': config, 'reasons': [], 'warnings': [], 'sources': [],
            'estimated_bytes': None, 'available_bytes': None, 'creates': 'A new timestamped snapshot; earlier files remain unchanged.'}
    if os.name != 'posix':
        plan['reasons'].append('Run drive checks on Linux; this plan does not execute Pi commands on Windows.')
        return plan
    if not config['uuid']:
        plan['reasons'].append('No backup disk configured yet. Attach the future external HDD, mount it, and select its UUID.')
        return plan
    try:
        guard = storage_guard(base)
        storage = guard.load_config(base / 'configs/storage.json')
        devices = device_map(storage, guard)
        manifest_all = read_json(base / 'manifest.json')
        manifest, selected, historical, unavailable = backup_manifest(base, manifest_all, storage, guard)
        groups = data_groups(base, manifest)
        required = backup_storage_keys(groups, storage, guard)
        # Mount identity is checked before any source path is accessed. The
        # directory requirement catches a selected app that was never fully
        # prepared instead of silently omitting its state from a backup.
        guard.check(required=required, manifest=manifest, config=storage, require_dirs=True)
        validate_backup_groups(groups)
        roots = source_list(base, manifest, devices, config['include_bulk'], groups)
        raw_databases = [Path(row['path']) for row in groups if row['kind'] == 'database']
        destination = exact_mount(config['mount'], config['uuid'], writable=True)
        if destination['fstype'] not in {'ext4', 'xfs', 'btrfs', 'exfat', 'ntfs', 'ntfs3', 'fuseblk'}:
            raise RuntimeError('Unsupported backup filesystem: ' + destination['fstype'])
        target_disks = physical_disks(destination['source'])
        for key in required:
            row = devices[key]
            # Even when bulk is omitted the backup cannot be another partition of a production disk.
            source = exact_mount(row['mount'], row.get('uuid'))
            if target_disks & physical_disks(source['source']):
                raise RuntimeError('Backup destination shares a physical disk with production storage: ' + key)
        if any(Path(config['mount']) == p or p in Path(config['mount']).parents for p in roots):
            raise RuntimeError('Backup destination is nested inside a source tree.')
        estimate = 1024 ** 3
        for path in roots:
            device = path.lstat().st_dev
            size = sum(details.st_size for _, details in walk_source(path, device) if stat.S_ISREG(details.st_mode))
            plan['sources'].append({'path': str(path), 'device_number': device, 'bytes': size})
            estimate += size
        for raw in raw_databases:
            if raw.exists():
                estimate += 2 * sum(s.st_size for _, s in walk_source(raw, raw.stat().st_dev) if stat.S_ISREG(s.st_mode))
        free = shutil.disk_usage(config['mount']).free
        plan.update(destination=destination, physical_disks=sorted(target_disks),
                    backup_apps=[app['name'] for app in manifest], selected_apps=selected,
                    historical_apps=historical,
                    estimated_bytes=estimate, available_bytes=free)
        if historical:
            plan['warnings'].append('Preserving configured data from deselected applications: ' +
                                    ', '.join(historical))
        if unavailable:
            plan['warnings'].append('Historical paths on retired/unconfigured storage were not accessed: ' +
                                    ', '.join(f'{app}:{path}' for app, path in unavailable))
        if free < estimate + config['reserve_gib'] * 1024 ** 3:
            raise RuntimeError('Backup disk needs estimated input size plus the configured free-space reserve.')
        if not config['include_bulk']:
            plan['warnings'].append('Bulk documents and media are excluded; this is not a full-server data backup.')
        if destination['fstype'] in {'ext4', 'xfs', 'btrfs'}:
            plan['warnings'].append('This Linux filesystem is not natively readable by Windows. Use Linux or appropriate filesystem tooling.')
        else:
            plan['warnings'].append('Filenames unsupported by this filesystem cause a failed snapshot; metadata is recorded separately.')
        plan['ready'] = True
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        plan['reasons'].append(str(error))
    return plan


@contextmanager
def pinned_folder(config, create=False):
    row = exact_mount(config['mount'], config['uuid'], writable=create)
    handles = []
    try:
        fd = os.open(config['mount'], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        handles.append(fd)
        if os.fstat(fd).st_dev != row['device_number']:
            raise RuntimeError('Backup mount changed before opening.')
        for component in relative_name(config['folder']).parts:
            if create:
                try:
                    os.mkdir(component, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            handles.append(fd)
            if os.fstat(fd).st_dev != row['device_number']:
                raise RuntimeError('Nested backup filesystem is not allowed.')
        yield Path('/proc/self/fd/' + str(fd)), row
    finally:
        for handle in reversed(handles):
            os.close(handle)


def containers():
    ids = output(['docker', 'ps', '-aq']).split()
    return json.loads(output(['docker', 'inspect', *ids])) if ids else []


def container_app(container):
    return container['Config'].get('Labels', {}).get('com.docker.compose.project', '').removeprefix('pi-')


def service_name(container):
    return container['Config'].get('Labels', {}).get('com.docker.compose.service', '')


def running(container):
    return container['State'].get('Running') or container['State']['Status'] in {'running', 'restarting', 'paused'}


def inventory(manifest, source_roots):
    known = {a['name'] for a in manifest}
    managed = []
    for container in containers():
        project = container['Config'].get('Labels', {}).get('com.docker.compose.project', '')
        if project.startswith('pi-') and container_app(container) in known:
            if container['State'].get('Paused'):
                raise RuntimeError('Unpause the managed container before backup: ' + container['Name'])
            managed.append(container)
        elif running(container):
            for mount in container.get('Mounts', []):
                path = Path(mount.get('Source', '/nonexistent'))
                if mount.get('RW') and any(path == root or path in root.parents or root in path.parents for root in source_roots):
                    raise RuntimeError('Unmanaged running container can write backup source data: ' + container['Name'])
    return managed


def wait_ready(container_id, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        item = json.loads(output(['docker', 'inspect', container_id]))[0]
        state = item['State']
        if state.get('Status') == 'running' and state.get('Health', {}).get('Status', 'healthy') == 'healthy':
            return
        time.sleep(2)
    raise RuntimeError('Container did not become ready: ' + container_id)


def guard_app(base, app):
    run([sys.executable, str(base / 'scripts/storage_guard.py'), '--app', app, '--directories'],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def resume(original, temporarily_started, base):
    errors = []
    for identifier in list(temporarily_started):
        try:
            run(['docker', 'stop', '-t', '120', identifier], stdout=subprocess.DEVNULL, timeout=150)
        except (OSError, subprocess.SubprocessError) as error:
            errors.append('Temporary database could not be stopped: ' + str(error))
    apps = {}
    for item in original:
        apps.setdefault(container_app(item), []).append(item)
    for app, items in apps.items():
        try:
            guard_app(base, app)
            # Never recreate services or start a previously stopped ID while recovering.
            backends = [item for item in items if service_name(item) in {'db', 'redis'}]
            for item in backends:
                run(['docker', 'start', item['Id']], stdout=subprocess.DEVNULL)
                wait_ready(item['Id'])
            for item in items:
                if item not in backends:
                    run(['docker', 'start', item['Id']], stdout=subprocess.DEVNULL)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            errors.append(app + ': restart withheld or failed: ' + str(error))
    return errors


def dump_databases(manifest, managed, destination, temporarily_started, base):
    rows = []
    destination.mkdir(mode=0o700)
    for app in manifest:
        db = app.get('database') or {}
        if db.get('type') not in {'postgres', 'mariadb'}:
            continue
        for value in [app['name'], db['name'], db['user'], db['service']]:
            if not re.fullmatch(r'[a-zA-Z0-9_.-]+', value):
                raise RuntimeError('Invalid database metadata.')
        matches = [c for c in managed if container_app(c) == app['name'] and service_name(c) == db['service']]
        if not matches:
            # The database's raw directory is intentionally excluded from
            # file copying. Re-check its selected storage immediately before
            # accepting an absent container as an uninitialized database, so
            # an unplugged custom SSD cannot look like an empty mountpoint.
            guard_app(base, app['name'])
            stored = database_paths(base, manifest, app['name'])
            if any(path.is_dir() and any(path.iterdir()) for path in stored):
                raise RuntimeError('Database files exist without their original database container: ' + app['name'])
            rows.append({'app': app['name'], 'status': 'uninitialized', 'database': db})
            continue
        if len(matches) != 1:
            raise RuntimeError('Expected exactly one database container: ' + app['name'])
        item = matches[0]
        guard_app(base, app['name'])
        identifier = item['Id']
        temporarily_started.add(identifier)
        run(['docker', 'start', identifier], stdout=subprocess.DEVNULL)
        wait_ready(identifier)
        name = app['name'] + '.sql'
        with (destination / name).open('xb') as handle:
            if db['type'] == 'postgres':
                run(['docker', 'exec', identifier, 'pg_dump', '-U', db['user'], '-d', db['name'],
                     '--format=plain', '--no-owner', '--no-acl'], stdout=handle, stderr=subprocess.PIPE, timeout=None)
            else:
                run(['docker', 'exec', '-e', 'BACKUP_DATABASE=' + db['name'], identifier, 'sh', '-c',
                     'MYSQL_PWD="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}" exec mariadb-dump -uroot --single-transaction --routines --events --triggers --hex-blob --skip-lock-tables "$BACKUP_DATABASE"'],
                    stdout=handle, stderr=subprocess.PIPE, timeout=None)
            handle.flush()
            os.fsync(handle.fileno())
        if (destination / name).stat().st_size == 0:
            raise RuntimeError('Database dump is empty: ' + app['name'])
        run(['docker', 'stop', '-t', '120', identifier], stdout=subprocess.DEVNULL, timeout=150)
        temporarily_started.remove(identifier)
        rows.append({'app': app['name'], 'status': 'dumped', 'database': db,
                     'file': 'databases/' + name, 'image': item['Config']['Image']})
    return rows


def metadata(path, details):
    row = {'path': str(path), 'mode': stat.S_IMODE(details.st_mode), 'uid': details.st_uid,
           'gid': details.st_gid, 'mtime_ns': details.st_mtime_ns, 'atime_ns': details.st_atime_ns}
    if stat.S_ISDIR(details.st_mode):
        row['type'] = 'directory'
    elif stat.S_ISREG(details.st_mode):
        row.update(type='file', size=details.st_size)
    elif stat.S_ISLNK(details.st_mode):
        row.update(type='symlink', target=os.readlink(path))
    elif stat.S_ISSOCK(details.st_mode):
        row['type'] = 'runtime-socket'
    else:
        raise RuntimeError('Unsupported special file in source tree: ' + str(path))
    row['xattrs'] = {}
    if hasattr(os, 'listxattr'):
        for name in os.listxattr(path, follow_symlinks=False):
            row['xattrs'][name] = base64.b64encode(os.getxattr(path, name, follow_symlinks=False)).decode('ascii')
    return row


def copy_sources(roots, destination):
    count = 0
    with (destination / 'metadata.jsonl').open('x', encoding='utf-8', newline='\n') as records:
        for root in roots:
            source = Path(root['path'])
            for path, details in walk_source(source, root['device_number']):
                row = metadata(path, details)
                if row['type'] == 'directory':
                    (destination / 'files' / str(path).lstrip('/')).mkdir(parents=True, exist_ok=True, mode=0o700)
                elif row['type'] == 'file':
                    stored = 'files/' + str(path).lstrip('/')
                    target = destination / stored
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                    with os.fdopen(fd, 'rb') as src, target.open('xb') as dst:
                        before = os.fstat(src.fileno())
                        if (before.st_dev, before.st_ino) != (details.st_dev, details.st_ino):
                            raise RuntimeError('Source changed before copy: ' + str(path))
                        digest = hashlib.sha256()
                        while block := src.read(BUFFER):
                            dst.write(block)
                            digest.update(block)
                        dst.flush()
                        os.fsync(dst.fileno())
                        after = os.fstat(src.fileno())
                        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                            raise RuntimeError('File changed during backup: ' + str(path))
                    row.update(stored=stored, sha256=digest.hexdigest())
                    count += 1
                records.write(json.dumps(row, ensure_ascii=True) + '\n')
        records.flush()
        os.fsync(records.fileno())
    return count


def sha256(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        while block := handle.read(BUFFER):
            value.update(block)
    return value.hexdigest()


def write_json(path, data):
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(data, handle, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())


def create(config, base=BASE):
    require_root()
    with server_lock():
        plan = make_plan(config, base)
        if not plan['ready']:
            raise RuntimeError('; '.join(plan['reasons']))
        manifest_all = read_json(base / 'manifest.json')
        selected_names = plan.get('backup_apps')
        if selected_names is None:
            manifest = manifest_all  # compatibility with older callers/tests
        else:
            manifest = [app for app in manifest_all if app['name'] in set(selected_names)]
            if {app['name'] for app in manifest} != set(selected_names):
                raise RuntimeError('Backup plan references applications missing from the current manifest.')
        managed = inventory(manifest, [Path(r['path']) for r in plan['sources']])
        original = [c for c in managed if running(c)]
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(4)
        temporary = set()
        resume_errors = []
        with pinned_folder(config, create=True) as (folder, mount):
            partial = folder / ('incomplete-' + stamp)
            partial.mkdir(mode=0o700)
            write_json(partial / 'original-containers.json',
                       [{'id': c['Id'], 'app': container_app(c), 'service': service_name(c)} for c in original])
            write_json(partial / 'manifest.json', manifest_all)
            write_json(partial / 'plan.json', plan)
            try:
                if original:
                    run(['docker', 'stop', '-t', '120', *[c['Id'] for c in original]],
                        stdout=subprocess.DEVNULL, timeout=max(180, len(original) * 130))
                dbs = dump_databases(manifest, managed, partial / 'databases', temporary, base)
                # Confirm all managed writers are stopped after temporary dump containers stop.
                now = inventory(manifest, [Path(r['path']) for r in plan['sources']])
                if any(running(c) for c in now):
                    raise RuntimeError('A managed container restarted during the backup.')
                count = copy_sources(plan['sources'], partial)
                info = {'format': FORMAT, 'created_utc': stamp, 'files': count, 'databases': dbs,
                        'source_roots': [r['path'] for r in plan['sources']],
                        'include_bulk': config['include_bulk'], 'warnings': plan['warnings'],
                        'selected_apps': plan.get('selected_apps'),
                        'historical_apps': plan.get('historical_apps', []),
                        'backup_uuid': config['uuid'], 'consistent_managed_containers': True,
                        'plain_files': True, 'raw_sql_server_databases_included': False}
                write_json(partial / 'backup.json', info)
            finally:
                resume_errors = resume(original, temporary, base)
                write_json(partial / 'resume.json', {'errors': resume_errors, 'original_ids': [c['Id'] for c in original]})
            # Hash after resuming services; these are immutable copied files and dumps.
            checksums = {}
            for path in sorted(partial.rglob('*')):
                if path.is_file():
                    checksums[path.relative_to(partial).as_posix()] = sha256(path)
            write_json(partial / 'checksums.json', checksums)
            verify(partial, require_complete=False)
            exact_mount(config['mount'], config['uuid'], writable=True)
            write_json(partial / 'COMPLETE', {'format': FORMAT, 'checksums_sha256': sha256(partial / 'checksums.json')})
            final = folder / stamp
            if final.exists():
                raise RuntimeError('Snapshot name collision; partial snapshot preserved.')
            partial.rename(final)
            os.sync()
            return {'complete': True, 'snapshot': str(Path(config['mount']) / config['folder'] / stamp),
                    'files': count, 'resume_errors': resume_errors, 'warnings': plan['warnings']}


def contained_file(snapshot, relative):
    relative_name(relative)
    path = snapshot.joinpath(*PurePosixPath(relative).parts)
    if not path.resolve().is_relative_to(snapshot.resolve()) or path.is_symlink():
        raise RuntimeError('Snapshot path escapes its directory: ' + relative)
    if not path.is_file():
        raise RuntimeError('Missing snapshot file: ' + relative)
    return path


def records(snapshot):
    seen = set()
    with contained_file(snapshot, 'metadata.jsonl').open(encoding='utf-8') as handle:
        for line in handle:
            row = json.loads(line)
            name = PurePosixPath(row['path'])
            if not name.is_absolute() or name.anchor != '/' or '..' in name.parts or str(name) != row['path'] or name == PurePosixPath('/') or '\\' in row['path']:
                raise RuntimeError('Unsafe original path in metadata.')
            if row['path'] in seen:
                raise RuntimeError('Duplicate original path in metadata.')
            seen.add(row['path'])
            if row['type'] not in {'file', 'directory', 'symlink', 'runtime-socket'}:
                raise RuntimeError('Unexpected metadata file type.')
            if row['type'] == 'file' and row.get('stored') != 'files/' + row['path'].lstrip('/'):
                raise RuntimeError('File storage path does not match original path.')
            if not isinstance(row['mode'], int) or row['mode'] < 0 or row['mode'] > 0o7777:
                raise RuntimeError('Invalid file mode in metadata.')
            for value in ['uid', 'gid', 'mtime_ns', 'atime_ns']:
                if not isinstance(row[value], int) or row[value] < 0:
                    raise RuntimeError('Invalid metadata ' + value)
            for value in row.get('xattrs', {}).values():
                base64.b64decode(value, validate=True)
            yield row


def verify(snapshot, require_complete=True):
    snapshot = Path(snapshot)
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise RuntimeError('Snapshot must be a real directory.')
    info = read_json(contained_file(snapshot, 'backup.json'))
    if info.get('format') != FORMAT:
        raise RuntimeError('Unsupported backup format.')
    checksum_file = contained_file(snapshot, 'checksums.json')
    if require_complete:
        complete = read_json(contained_file(snapshot, 'COMPLETE'))
        if complete.get('format') != FORMAT or complete.get('checksums_sha256') != sha256(checksum_file):
            raise RuntimeError('Snapshot completion marker or checksum index is invalid.')
    checksums = read_json(checksum_file)
    required = {'backup.json', 'metadata.jsonl', 'manifest.json', 'plan.json', 'resume.json', 'original-containers.json'}
    if not required <= checksums.keys():
        raise RuntimeError('Checksum index is missing recovery metadata.')
    for relative, digest in checksums.items():
        if not re.fullmatch('[a-f0-9]{64}', digest) or sha256(contained_file(snapshot, relative)) != digest:
            raise RuntimeError('Checksum mismatch: ' + relative)
    actual = set()
    for path in snapshot.rglob('*'):
        if path.is_symlink():
            raise RuntimeError('Snapshot must not contain physical symlinks.')
        relative = path.relative_to(snapshot).as_posix()
        if path.is_file() and relative not in {'COMPLETE', 'checksums.json'}:
            actual.add(relative)
    if actual != set(checksums):
        raise RuntimeError('Snapshot contains unindexed files or is missing indexed files.')
    count = 0
    total = 0
    for row in records(snapshot):
        if row['type'] == 'file':
            if checksums.get(row['stored']) != row['sha256']:
                raise RuntimeError('File metadata disagrees with checksum index.')
            if contained_file(snapshot, row['stored']).stat().st_size != row['size']:
                raise RuntimeError('File size mismatch: ' + row['stored'])
            total += row['size']
            count += 1
    for db in info['databases']:
        if db['status'] == 'dumped' and db['file'] not in checksums:
            raise RuntimeError('Database dump is absent from checksum index.')
    if count != info['files']:
        raise RuntimeError('File count differs from snapshot metadata.')
    return {'verified': True, 'format': FORMAT, 'files': count, 'bytes': total,
            'created_utc': info['created_utc'], 'databases': info['databases'],
            'source_roots': info['source_roots'], 'include_bulk': info['include_bulk']}


def restore_plan(snapshot, destination=None):
    result = verify(snapshot)
    result.update(action='restore-to-staging', destination=str(destination) if destination else None,
                  map=[{'original': p, 'staged': str(Path(destination) / 'files' / p.lstrip('/')) if destination else 'files/' + p.lstrip('/')}
                       for p in result['source_roots']],
                  notes=['Files are restored under a new staging directory; active application paths are never overwritten.',
                         'SQL dumps are copied for a separate, reviewed database import into compatible empty databases.',
                         'Symlinks remain recovery metadata; staging restore never materializes links outside the snapshot.',
                         'Only restore your own trusted backup. Checksums detect corruption, not malicious replacement.'])
    return result


def restore_metadata(path, row):
    os.chown(path, row['uid'], row['gid'])
    os.chmod(path, row['mode'])
    for name, value in row.get('xattrs', {}).items():
        os.setxattr(path, name, base64.b64decode(value, validate=True), follow_symlinks=False)
    os.utime(path, ns=(row['atime_ns'], row['mtime_ns']), follow_symlinks=False)


def stage_files(snapshot, pinned):
    """Copy verified files into a newly created, private staging directory."""
    deferred = []
    skipped = []
    for row in records(snapshot):
        target = pinned / 'files' / row['path'].lstrip('/')
        if row['type'] == 'directory':
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            deferred.append((target, row))
        elif row['type'] == 'file':
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with contained_file(snapshot, row['stored']).open('rb') as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst, BUFFER)
                dst.flush()
                os.fsync(dst.fileno())
            if sha256(target) != row['sha256']:
                raise RuntimeError('Staged file checksum differs: ' + row['path'])
            deferred.append((target, row))
        else:
            skipped.append(row)
    # Children first so directory timestamps and permissions survive restoration.
    for path, row in sorted(deferred, key=lambda pair: len(pair[0].parts), reverse=True):
        restore_metadata(path, row)
    for name in ['databases', 'backup.json', 'manifest.json', 'metadata.jsonl']:
        src = snapshot / name
        if src.is_dir():
            shutil.copytree(src, pinned / name)
        else:
            shutil.copyfile(src, pinned / name)
    write_json(pinned / 'links-and-runtime-files.json', skipped)
    return skipped


def restore(snapshot, destination, uuid):
    require_root()
    if not uuid:
        raise RuntimeError('Specify --destination-uuid for the staging filesystem.')
    snapshot = no_symlink(Path(snapshot).absolute())
    destination = no_symlink(Path(destination).absolute())
    result = restore_plan(snapshot, destination)
    if destination.exists():
        raise RuntimeError('Staging destination must be a new directory; existing directories are never overwritten.')
    if not destination.parent.is_dir():
        raise RuntimeError('Staging parent directory must already exist on the mounted recovery disk.')
    if destination == snapshot or snapshot in destination.parents or destination in snapshot.parents:
        raise RuntimeError('Staging destination must be separate from the snapshot.')
    for source in result['source_roots']:
        root = Path(source)
        if destination == root or root in destination.parents or destination in root.parents:
            raise RuntimeError('Refusing to restore into an active/original source location: ' + str(destination))
    mount = json.loads(output(['findmnt', '--json', '--target', str(destination.parent),
                              '--output', 'TARGET,SOURCE,UUID,FSTYPE,OPTIONS']))['filesystems'][0]
    checked = exact_mount(mount['target'], uuid, writable=True)
    if mount['fstype'] not in {'ext4', 'xfs', 'btrfs'}:
        raise RuntimeError('Restore staging requires a Linux filesystem that supports POSIX permissions and xattrs.')
    if shutil.disk_usage(destination.parent).free < result['bytes'] + 2 * 1024 ** 3:
        raise RuntimeError('Staging filesystem lacks input size plus 2 GiB free reserve.')
    parent_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(parent_fd).st_dev != checked['device_number']:
            raise RuntimeError('Recovery filesystem changed before staging.')
        os.mkdir(destination.name, 0o700, dir_fd=parent_fd)
        pinned = Path('/proc/self/fd/' + str(parent_fd)) / destination.name
        skipped = stage_files(snapshot, pinned)
        result.update(restored=True, links_held_for_review=len(skipped), active_files_modified=False)
        write_json(pinned / 'STAGING-RESTORE.json', result)
        exact_mount(mount['target'], uuid, writable=True)
        os.sync()
        return result
    finally:
        os.close(parent_fd)


def resolve_snapshot(args, config):
    if args.snapshot:
        return no_symlink(Path(args.snapshot).absolute())
    if not args.backup or not re.fullmatch(r'[A-Za-z0-9_.-]+', args.backup):
        raise RuntimeError('Specify --snapshot PATH or --backup SNAPSHOT_NAME.')
    if not config['uuid']:
        raise RuntimeError('No backup disk is configured.')
    exact_mount(config['mount'], config['uuid'])
    return no_symlink(Path(config['mount']) / config['folder'] / args.backup)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'create', 'verify', 'restore-plan', 'restore'])
    parser.add_argument('--config', default=str(BASE / 'configs/portable-backup.json'))
    parser.add_argument('--backup')
    parser.add_argument('--snapshot', help='Standalone recovery path; does not require /srv/docker or Docker.')
    parser.add_argument('--destination')
    parser.add_argument('--destination-uuid')
    parser.add_argument('--json', action='store_true', help='JSON is also the default output format.')
    args = parser.parse_args()
    config = load_config(args.config) if not args.snapshot else dict(DEFAULT)
    if args.action == 'plan':
        result = make_plan(config)
    elif args.action == 'create':
        def interrupted(signum, frame):
            raise InterruptedError('Backup interrupted by signal ' + str(signum))
        signal.signal(signal.SIGTERM, interrupted)
        result = create(config)
    else:
        snapshot = resolve_snapshot(args, config)
        if args.action == 'verify':
            result = verify(snapshot)
        elif args.action == 'restore-plan':
            result = restore_plan(snapshot, args.destination)
        else:
            if not args.destination:
                raise RuntimeError('Restore requires --destination NEW_EMPTY_STAGING_PATH.')
            result = restore(snapshot, args.destination, args.destination_uuid)
    print(json.dumps(result, indent=2))
    return 1 if result.get('resume_errors') else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({'success': False, 'error': str(error)}))
        raise SystemExit(1)
