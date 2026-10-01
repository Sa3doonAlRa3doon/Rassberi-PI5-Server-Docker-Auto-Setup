#!/usr/bin/env python3
"""Read-only disk discovery, reviewed placement plans and explicit copy migrations.

The control plane stays at /srv/docker. Application state and bulk files are
independently assignable. Discovery reads block metadata, never user files.
"""
import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import tempfile

from docker_restart import restart_policy_option
import storage_guard as guard

BASE = Path(__file__).resolve().parents[1]
SAFE_PATH = re.compile(r'/[A-Za-z0-9_./-]+\Z')


def deployed_layout(base):
    return base.resolve() == Path('/srv/docker')


def mapped_path(path, replacements):
    for before, after in sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True):
        if path == before or path.startswith(before + '/'):
            return after + path[len(before):]
    return path


def overlaps(first, second):
    return first == second or first.startswith(second + '/') or second.startswith(first + '/')


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def container_identity(container):
    labels = container.get('Config', {}).get('Labels', {})
    project = labels.get('com.docker.compose.project')
    service = labels.get('com.docker.compose.service')
    if not isinstance(project, str) or not project.startswith('pi-') or not isinstance(service, str) or not service:
        raise RuntimeError('Saved container has no managed Compose identity')
    return project, service


def live_containers():
    """Read current container IDs after Compose may have recreated a service."""
    ids = run(['docker', 'ps', '-aq'], capture_output=True, text=True).stdout.split()
    return json.loads(run(['docker', 'inspect', *ids], capture_output=True, text=True).stdout) if ids else []


def restore_restart_policies(saved_containers, current_containers=None):
    """Undo temporary restart=no, including containers recreated by Compose."""
    current_containers = list(saved_containers if current_containers is None else current_containers)
    policies = {}
    for container in saved_containers:
        identity = container_identity(container)
        policy = restart_policy_option(container.get('HostConfig', {}).get('RestartPolicy'))
        if identity in policies and policies[identity] != policy:
            raise RuntimeError('Conflicting saved Docker restart policies for ' + '/'.join(identity))
        policies[identity] = policy
    current = {}
    for container in current_containers:
        try:
            current.setdefault(container_identity(container), []).append(container)
        except RuntimeError:
            continue
    failures = []
    for identity, policy in policies.items():
        targets = current.get(identity, [])
        if not targets:
            failures.append(('/'.join(identity), RuntimeError('container no longer exists')))
            continue
        for container in targets:
            try:
                run(['docker', 'update', '--restart=' + policy, container['Id']], stdout=subprocess.DEVNULL)
            except (RuntimeError, KeyError, subprocess.SubprocessError) as exc:
                failures.append((container.get('Id', '<unknown>'), exc))
    if failures:
        ids = ', '.join(identifier for identifier, _ in failures)
        raise RuntimeError('Could not restore Docker restart policy for: ' + ids) from failures[0][1]


def read_json(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default


def atomic_json(path, value, mode=0o600):
    atomic_bytes(path, (json.dumps(value, indent=2) + '\n').encode(), mode)


def atomic_bytes(path, content, mode=0o600):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path.absolute():
        raise RuntimeError('Symlinked configuration target: ' + str(path))
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


def flatten(items, parent=None):
    for item in items:
        yield item, parent
        yield from flatten(item.get('children', []), item if item.get('type') == 'disk' else parent)


def discover():
    """No mounting, file enumeration, import, formatting or directory creation."""
    data = json.loads(run(['lsblk', '--json', '--bytes', '--paths', '--output',
        'NAME,TYPE,SIZE,FSTYPE,UUID,LABEL,MOUNTPOINTS,RO,ROTA,TRAN,MODEL'], capture_output=True, text=True).stdout)
    result = []
    for item, parent in flatten(data.get('blockdevices', [])):
        disk = parent or item
        for mount in item.get('mountpoints') or [None]:
            row = {key: item.get(key) for key in ('name', 'type', 'size', 'fstype', 'uuid', 'label')}
            row.update(mount=mount, model=(disk.get('model') or '').strip(), physical=disk.get('name'),
                       rotational=bool(disk.get('rota')), transport=disk.get('tran'), eligible=False)
            if not mount:
                row['reason'] = 'Not mounted. Mount this existing filesystem yourself before selecting it.'
            elif item.get('ro') or item.get('fstype') != 'ext4' or not item.get('uuid'):
                row['reason'] = 'Application storage requires a writable ext4 filesystem with a UUID.'
            elif mount != '/' and (not SAFE_PATH.fullmatch(mount) or not mount.startswith(('/mnt/', '/media/'))):
                row['reason'] = 'Use a stable mount below /mnt or /media, or the root filesystem.'
            else:
                try:
                    mounted = guard.mounted(mount)
                    if mounted.get('uuid') != item['uuid'] or 'rw' not in mounted.get('options', '').split(','):
                        raise RuntimeError('Mount identity or writable state changed')
                    if os.path.realpath(mount) != mount:
                        raise RuntimeError('Symlinked mount path')
                    fs = os.statvfs(mount)
                    row.update(free_bytes=fs.f_bavail * fs.f_frsize, eligible=True,
                        kind='microSD' if 'mmcblk' in disk['name'] else 'HDD' if disk.get('rota') else 'SSD')
                except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
                    row['reason'] = str(exc)
            result.append(row)
    return result


def catalog(base=BASE, selected=None):
    manifest = read_json(base / 'manifest.json')
    if selected is not None:
        selected = set(selected)
    rows = {}
    saved = read_json(base / 'configs/layout.json', {}).get('placements', {})
    if len(set(saved.values())) != len(saved):
        raise RuntimeError('Saved layout contains duplicate placement destinations')
    reverse = {v: k for k, v in saved.items()}
    for app in manifest:
        if selected is not None and app['name'] not in selected:
            continue
        for directory in app.get('directories', []):
            path = directory['path']
            original = mapped_path(path, reverse)
            if not original.startswith(('/srv/docker/appdata/', '/srv/docker/databases/', '/mnt/')):
                continue
            # The metrics sidecar is part of the fixed management plane.
            if original == '/srv/docker/appdata/storage-metrics':
                continue
            row = rows.setdefault(original, dict(id=original, current=path, apps=[],
                kind='database' if original.startswith('/srv/docker/databases/') else
                     'appdata' if original.startswith('/srv/docker/appdata/') else 'bulk'))
            row['apps'] = sorted(set(row['apps'] + [app['name']]))
    # Parent/child data paths are one placement to preserve shared-tree semantics.
    result = []
    for key, row in sorted(rows.items(), key=lambda pair: len(pair[0])):
        parent = next((r for r in result if key.startswith(r['id'] + '/')), None)
        if parent:
            if row['current'] != parent['current'] + key[len(parent['id']):]:
                raise RuntimeError('Parent/child placement drift; review the manifest: ' + key)
            parent['apps'] = sorted(set(parent['apps'] + row['apps']))
        else:
            result.append(row)
    return sorted(result, key=lambda r: (r['kind'], r['id']))


def auto_select(disks, entries, backup_uuid=None):
    """Suggest paths only. Choosing a path does not read/import its contents."""
    choices = [d for d in disks if d.get('eligible') and d.get('uuid') != backup_uuid]
    root = next((d for d in choices if d['mount'] == '/'), None)
    if not root:
        raise RuntimeError('A writable ext4 root filesystem with UUID is required')
    ssds = [d for d in choices if d.get('kind') == 'SSD']
    if not ssds:
        raise RuntimeError('No mounted SSD for databases/appdata. Mount an SSD before auto selection.')
    fast = next((d for d in ssds if d['mount'] == '/'), max(ssds, key=lambda d: d.get('free_bytes', 0)))
    hdds = [d for d in choices if d.get('kind') == 'HDD']
    cards = [d for d in choices if d.get('kind') == 'microSD']
    bulk = max(hdds or ssds, key=lambda d: d.get('free_bytes', 0))
    media = max(cards or [bulk], key=lambda d: d.get('free_bytes', 0))
    proposed = {}
    # A fresh namespace prevents auto selection from adopting existing server data.
    suffix = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    for row in entries:
        drive = fast if row['kind'] != 'bulk' else media if row['id'].startswith('/mnt/media/') else bulk
        prefix = '/srv/pi-data' if drive['mount'] == '/' else drive['mount'] + '/PiServer'
        leaf = row['id'].removeprefix('/srv/docker/').removeprefix('/mnt/')
        proposed[row['id']] = prefix + '/' + suffix + '/' + leaf
    return proposed


def replace_paths(value, replacements):
    if isinstance(value, str):
        return mapped_path(value, replacements)
    if isinstance(value, dict):
        return {k: replace_paths(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_paths(v, replacements) for v in value]
    return value


def validate_destination(path, disks):
    if not isinstance(path, str) or not SAFE_PATH.fullmatch(path) or posixpath.normpath(path) != path:
        raise RuntimeError('Use a normalized absolute path with letters, numbers, slash, dot, dash or underscore')
    options = [d for d in disks if d.get('eligible') and
               (d['mount'] == '/' or path.startswith(d['mount'] + '/'))]
    if not options:
        raise RuntimeError('Destination is not on an eligible mounted filesystem: ' + path)
    drive = max(options, key=lambda d: len(d['mount']))
    if drive['mount'] == '/' and not path.startswith('/srv/pi-data/') and not path.startswith(('/srv/docker/appdata/', '/srv/docker/databases/')):
        raise RuntimeError('Root data paths must be under /srv/pi-data, /srv/docker/appdata or /srv/docker/databases')
    if path == drive['mount']:
        raise RuntimeError('Choose a dedicated server subdirectory, not the drive root: ' + path)
    if os.path.realpath(path) != path:
        raise RuntimeError('Symlinks are not allowed in destination paths: ' + path)
    ancestor = Path(path)
    while not ancestor.exists():
        ancestor = ancestor.parent
    actual = guard.containing_mount(str(ancestor))
    exact = guard.mounted(drive['mount'])
    if (actual['target'] != drive['mount'] or actual.get('uuid') != drive['uuid'] or
            exact.get('target') != drive['mount'] or exact.get('uuid') != drive['uuid']):
        raise RuntimeError('Destination resolves onto another filesystem: ' + path)
    if any(item.get('fstype') != 'ext4' or 'rw' not in item.get('options', '').split(',') for item in (actual, exact)):
        raise RuntimeError('Destination filesystem must still be writable ext4: ' + path)
    if os.path.lexists(path) and not Path(path).is_dir():
        raise RuntimeError('Destination must be a directory: ' + path)
    return drive


def source_state(path, base, inspect_size=True):
    """Verify identity before even listing the existing application directory."""
    config = base / 'configs/storage.json'
    guard.check([guard.path_key(path, config)], manifest=[], config=config)
    guard.assert_path(path, base / 'configs/storage.json')
    source = Path(path)
    exists = source.is_dir()
    if not exists:
        return False, False, 0
    nested = json.loads(run(['findmnt', '--json', '--submounts', '--target', path,
        '-o', 'TARGET'], capture_output=True, text=True).stdout)
    if any(row.get('target', '').startswith(path + '/') for row, _ in flatten(nested.get('filesystems', []))):
        raise RuntimeError('Source contains a nested mount; review separately: ' + path)
    populated = any(source.iterdir())
    size = int(run(['du', '-sx', '--block-size=1', path], capture_output=True, text=True).stdout.split()[0]) if populated and inspect_size else 0
    return exists, populated, size


def plan(placements, base=BASE, disks=None):
    disks = discover() if disks is None else disks
    manifest_all = read_json(base / 'manifest.json')
    try:
        import app_selection
        selected = app_selection.installed_names(base, manifest_all)
    except ImportError:
        selected = None
    entries = catalog(base, selected)
    known = {r['id']: r for r in entries}
    if not isinstance(placements, dict) or set(placements) != set(known):
        raise RuntimeError('Placement plan must include every displayed data group exactly once')
    if any(not isinstance(path, str) for path in placements.values()):
        raise RuntimeError('Placement destinations must be strings')
    targets = sorted(placements.values())
    for i, path in enumerate(targets):
        if any(overlaps(path, other) for other in targets[i+1:]):
            raise RuntimeError('Data destinations may not overlap: ' + path)
    root = next((d for d in disks if d.get('eligible') and d['mount'] == '/'), None)
    if not root:
        raise RuntimeError('Cannot identify writable ext4 root')
    devices = {'root': dict(mount='/', uuid=root['uuid'], filesystem='ext4', kind=root.get('kind'))}
    deployed = deployed_layout(base)
    changes, replacements = [], {}
    backup = read_json(base / 'configs/portable-backup.json', {})
    required_bytes = {}
    for key, path in placements.items():
        row = known[key]
        drive = validate_destination(path, disks)
        if overlaps(path, '/srv/docker/appdata/storage-metrics'):
            raise RuntimeError('The storage metrics directory belongs to the fixed control plane')
        if drive.get('uuid') == backup.get('uuid'):
            raise RuntimeError('The backup filesystem cannot also hold active application data')
        if row['kind'] in {'database', 'appdata'} and drive.get('kind') != 'SSD':
            raise RuntimeError('Databases and application state require SSD storage: ' + key)
        name = 'root' if drive['mount'] == '/' else 'disk_' + hashlib.sha256(drive['uuid'].encode()).hexdigest()[:10]
        if drive['mount'] != '/' and drive['uuid'] == root['uuid']:
            raise RuntimeError('An alternate mount of the root filesystem is not a separate data device')
        if name in devices and devices[name]['mount'] != drive['mount']:
            raise RuntimeError('One filesystem UUID cannot have multiple selected mount points')
        devices[name] = dict(mount=drive['mount'], uuid=drive['uuid'], filesystem='ext4', kind=drive.get('kind'))
        if path != row['current']:
            if any(overlaps(path, item['current']) for item in entries):
                raise RuntimeError('New destinations must not overlap current application data: ' + path)
            if os.path.lexists(path):
                raise RuntimeError('New destination already exists; choose a new empty path: ' + path)
            # A fresh package never inspects/adopts pre-existing data from another install.
            exists, populated, size = source_state(row['current'], base) if deployed else (False, False, 0)
            required_bytes[name] = required_bytes.get(name, 0) + size
            changes.append(dict(source=row['current'], destination=path, source_exists=exists, populated=populated,
                                estimated_bytes=size, apps=row['apps'], drive=name))
            replacements[row['current']] = path
    for key, needed in required_bytes.items():
        drive = next(d for d in disks if d.get('uuid') == devices[key]['uuid'])
        if needed + 2 * 1024**3 > drive.get('free_bytes', 0):
            raise RuntimeError('Insufficient space for copies plus 2 GiB reserve: ' + devices[key]['mount'])
    # Unchanged data on old mounts is included above; optional unused drives are not dependencies.
    config = {'version': 2, 'devices': devices}
    guard.load_config(config)
    manifest = copy.deepcopy(manifest_all)
    selected_names = set(selected) if selected is not None else None
    for app in manifest:
        # A custom fresh install deliberately has no placement or configured
        # mount for apps the owner did not select.  Leave those entries
        # completely unchanged: changing their paths or deriving requirements
        # against the selected-only storage config would either adopt data that
        # was never reviewed or fail on an intentionally absent mount.
        if selected_names is not None and app['name'] not in selected_names:
            continue
        for directory in app.get('directories', []):
            directory['path'] = mapped_path(directory['path'], replacements)
        if (app.get('database') or {}).get('path'):
            app['database']['path'] = mapped_path(app['database']['path'], replacements)
        app['mounts'] = [k for k in guard.app_requirements(app, config) if k != 'root']
    return dict(changes=changes, storage=config, manifest=manifest, replacements=replacements,
                selected_apps=sorted(selected_names) if selected_names is not None else None,
                placements=placements, requires_copy=any(c['populated'] for c in changes),
                note='No source files are deleted. New destinations never adopt existing data.')


def python_paths(source, replacements):
    """Edit Path literals, keeping comments, credentials and unrelated text intact."""
    tree = ast.parse(source)
    aliases = {}

    def path_value(node):
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if name == 'Path' and len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                return node.args[0].value
        if isinstance(node, ast.Name):
            return aliases.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            prefix = path_value(node.left)
            if prefix and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
                return posixpath.join(prefix, node.right.value)
        return None

    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            value = path_value(statement.value)
            if value:
                aliases[statement.targets[0].id] = value
    lines = source.splitlines(keepends=True)
    offsets, total = [], 0
    for line in lines:
        offsets.append(total)
        total += len(line)
    edits = []

    def position(line, column):
        return offsets[line - 1] + len(lines[line - 1].encode('utf-8')[:column].decode('utf-8'))

    def visit(node):
        value = path_value(node) if isinstance(node, (ast.Call, ast.BinOp)) else None
        target = mapped_path(value, replacements) if value else value
        if target != value:
            # Preserve the existing Path constructor where possible (including pathlib.Path).
            constructor = ast.get_source_segment(source, node.func) if isinstance(node, ast.Call) else 'Path'
            edits.append((position(node.lineno, node.col_offset), position(node.end_lineno, node.end_col_offset), constructor + '(' + repr(target) + ')'))
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    ast.parse(source)
    return source


def render_files(base, replacements, selected_apps=None):
    """Rewrite reviewed host paths without changing unselected app projects."""
    result = {}
    if not replacements:
        return result
    selected_apps = None if selected_apps is None else set(selected_apps)
    for folder in ('compose', 'configs'):
        root = base / folder
        if root.is_symlink() or root.resolve() != root.absolute():
            raise RuntimeError('Symlinked deployment directory: ' + str(root))
        for path in root.rglob('*'):
            if not path.is_file() or 'release' in path.parts:
                continue
            if path.is_symlink() or path.resolve() != path.absolute():
                raise RuntimeError('Symlinked deployment file: ' + str(path))
            if path.name not in {'compose.yml', 'compose.yaml', '.env', '.env.example'} and not (folder == 'compose' and path.suffix == '.py'):
                continue
            # Compose projects are app-specific. An unselected app may refer
            # to a child of a selected app's data tree, so an ancestor path
            # replacement must not silently edit its inactive configuration.
            if folder == 'compose' and selected_apps is not None:
                relative = path.relative_to(root)
                if relative.parts and relative.parts[0] not in selected_apps:
                    continue
            old = path.read_text(encoding='utf-8')
            new = old
            if path.name in {'compose.yml', 'compose.yaml'}:
                try:
                    config = json.loads('\n'.join(line for line in old.splitlines() if not line.lstrip().startswith('#')))
                except json.JSONDecodeError as exc:
                    if any(before in old for before in replacements):
                        raise RuntimeError('Custom YAML Compose needs a reviewed host-path edit: ' + str(path)) from exc
                    continue
                changed = False
                for service in config.get('services', {}).values():
                    for volume in service.get('volumes', []):
                        if isinstance(volume, dict) and volume.get('type') == 'bind' and isinstance(volume.get('source'), str):
                            target = mapped_path(volume['source'], replacements)
                            changed |= target != volume['source']
                            volume['source'] = target
                if changed:
                    new = json.dumps(config, indent=2) + '\n'
            elif path.name in {'.env', '.env.example'}:
                rows = []
                for line in old.splitlines(keepends=True):
                    entry = re.fullmatch(r'([A-Z][A-Z0-9_]*(?:_PATH|_DIR|_ROOT))=(.*?)(\r?\n|$)', line)
                    if entry and not re.search(r'PASS|TOKEN|SECRET|KEY|CREDENTIAL', entry[1]):
                        value = entry[2]
                        quote = value[0] if len(value) > 1 and value[0] in "\"'" and value[-1] == value[0] else ''
                        raw = value[1:-1] if quote else value
                        line = entry[1] + '=' + quote + mapped_path(raw, replacements) + quote + entry[3]
                    rows.append(line)
                new = ''.join(rows)
            else:
                new = python_paths(old, replacements)
            if new != old:
                result[path] = new.encode('utf-8')
    return result


def directory_owners(base, manifest, target):
    """Resolve declarations from existing private env files without executing them."""
    owners = {}
    for app in manifest:
        values = {**app.get('env', {})}
        envfile = base / 'compose' / app['name'] / '.env'
        if envfile.is_symlink():
            raise RuntimeError('Symlinked environment file: ' + str(envfile))
        if envfile.exists():
            for line in envfile.read_text().splitlines():
                if line and not line.lstrip().startswith('#') and '=' in line:
                    name, value = line.split('=', 1)
                    if name in {'PUID', 'PGID'}:
                        values[name] = value.strip().strip("\"'")
        for directory in app.get('directories', []):
            path = directory['path']
            if path != target and not path.startswith(target + '/'):
                continue
            def numeric(value):
                text = str(value)
                for key in ('PUID', 'PGID'):
                    text = text.replace('${' + key + '}', str(values.get(key, 1000))).replace(key, str(values.get(key, 1000)))
                if not text.isdigit():
                    raise RuntimeError('Invalid directory owner for ' + path)
                return int(text)
            value = (numeric(directory.get('uid', 0)), numeric(directory.get('gid', 0)), int(directory.get('mode', '0750'), 8))
            if path in owners and owners[path] != value:
                raise RuntimeError('Conflicting directory ownership declarations: ' + path)
            owners[path] = value
    return owners


def apply(placements, migrate=False, base=BASE):
    """Caller owns /run/lock/pi-server.lock; all mutation follows a fresh plan."""
    proposal = plan(placements, base)
    if proposal['requires_copy'] and not migrate:
        raise RuntimeError('Existing data requires the explicit Copy existing data option; originals will be kept')
    deployed = deployed_layout(base)
    affected = set(a for change in proposal['changes'] for a in change['apps'])
    saved_containers = []
    if deployed:
        all_containers = live_containers()
        for container in all_containers:
            project = container.get('Config', {}).get('Labels', {}).get('com.docker.compose.project', '')
            managed = project.startswith('pi-') and project[3:] in affected
            if managed:
                saved_containers.append(container)
            elif container.get('State', {}).get('Status') in {'running', 'restarting', 'paused'}:
                if any(overlaps(mount.get('Source', ''), change['source']) for mount in container.get('Mounts', []) for change in proposal['changes']):
                    raise RuntimeError('Another running container uses migration data: ' + container['Id'])
        if any(c.get('State', {}).get('Status') == 'paused' for c in saved_containers):
            raise RuntimeError('Unpause or stop affected containers before migrating their data')
    files = render_files(base, proposal['replacements'], proposal['selected_apps'])
    files[base / 'manifest.json'] = (json.dumps(proposal['manifest'], indent=2) + '\n').encode()
    files[base / 'configs/storage.json'] = (json.dumps(proposal['storage'], indent=2) + '\n').encode()
    files[base / 'configs/layout.json'] = (json.dumps({'placements': placements}, indent=2) + '\n').encode()
    ownership = {change['destination']: directory_owners(base, proposal['manifest'], change['destination']) for change in proposal['changes']}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    recovery = base / 'backups' / ('layout-' + stamp)
    recovery.mkdir(parents=True, mode=0o700)
    for path in files:
        if path.exists():
            dest = recovery / path.relative_to(base)
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(path, dest)
    atomic_json(recovery / 'plan.json', {k: v for k, v in proposal.items() if k != 'manifest'})
    atomic_json(recovery / 'containers.json', saved_containers)
    committed = False
    written = []
    try:
        for container in saved_containers:
            run(['docker', 'update', '--restart=no', container['Id']], stdout=subprocess.DEVNULL)
        for container in saved_containers:
            if container['State']['Status'] in {'running', 'restarting'}:
                run(['docker', 'stop', '--time', '120', container['Id']], stdout=subprocess.DEVNULL)
        for change in proposal['changes'] if deployed else []:
            target = Path(change['destination'])
            guard.check([change['drive']], manifest=[], config=proposal['storage'])
            guard.assert_path(str(target), proposal['storage'])
            if os.path.lexists(target):
                raise RuntimeError('Destination appeared after review: ' + str(target))
            source_exists, populated, _ = source_state(change['source'], base, inspect_size=False)
            if change.get('source_exists') and not source_exists:
                raise RuntimeError('Source disappeared after review: ' + change['source'])
            if populated and not migrate:
                raise RuntimeError('Data appeared after review; explicit Copy existing data is required')
            target.mkdir(parents=True, mode=0o750)
            guard.assert_path(change['destination'], proposal['storage'], must_exist=True)
            if source_exists:
                cmd = ['rsync', '-aHAX', '--numeric-ids', '--one-file-system', change['source'] + '/', str(target) + '/']
                run(cmd)
                verify = run(['rsync', '-aHAXnci', '--delete', '--numeric-ids', '--one-file-system', change['source'] + '/', str(target) + '/'], capture_output=True, text=True)
                if verify.stdout.strip():
                    raise RuntimeError('Copy verification found differences; original retained: ' + str(target))
            for path, (uid, gid, mode) in sorted(ownership[change['destination']].items(), key=lambda item: len(item[0])):
                directory = Path(path)
                if not directory.exists() or (path == change['destination'] and not source_exists):
                    guard.assert_path(path, proposal['storage'])
                    directory.mkdir(parents=True, exist_ok=True, mode=mode)
                    os.chown(directory, uid, gid)
                    directory.chmod(mode)
            guard.check([change['drive']], manifest=[], config=proposal['storage'])
            guard.assert_path(change['destination'], proposal['storage'], must_exist=True)
        for path, content in files.items():
            atomic_bytes(path, content, (path.stat().st_mode & 0o777) if path.exists() else 0o600)
            written.append(path)
        committed = True
    finally:
        if not committed:
            for path in reversed(written):
                saved = recovery / path.relative_to(base)
                if saved.exists():
                    atomic_bytes(path, saved.read_bytes(), saved.stat().st_mode & 0o777)
                else:
                    path.unlink(missing_ok=True)
            restore_restart_policies(saved_containers)
            for c in saved_containers:
                if c['State']['Status'] in {'running', 'restarting'}:
                    app = c['Config']['Labels']['com.docker.compose.project'][3:]
                    run(['python3', str(base / 'scripts/storage_guard.py'), '--app', app, '--directories'])
                    run(['docker', 'start', c['Id']], stdout=subprocess.DEVNULL)
    restarted = []
    def reconcile_restart_policies():
        if saved_containers:
            restore_restart_policies(saved_containers, live_containers())

    try:
        if deployed:
            run(['python3', str(base / 'scripts/prepare.py'), str(base)])
            for app in sorted(affected):
                running = sorted({c['Config']['Labels']['com.docker.compose.service'] for c in saved_containers
                    if c['Config']['Labels']['com.docker.compose.project'] == 'pi-' + app and c['State']['Status'] in {'running', 'restarting'}})
                if running:
                    run(['python3', str(base / 'scripts/storage_guard.py'), '--app', app, '--directories'])
                    run(['docker', 'compose', '--project-name', 'pi-' + app, '--project-directory', str(base / 'compose' / app),
                         '--env-file', str(base / 'compose' / app / '.env'), '-f', str(base / 'compose' / app / 'compose.yml'),
                         'up', '-d', '--no-deps', '--wait', '--wait-timeout', '1200', *running])
                    restarted.append(app)
    except Exception as failure:
        try:
            reconcile_restart_policies()
        except Exception as restore_failure:
            raise RuntimeError(
                'Restart failed: ' + str(failure) + '; Docker restart-policy reconciliation also failed: ' +
                str(restore_failure)
            ) from failure
        raise
    else:
        # Compose may recreate a service whose bind source changed. Apply the
        # saved restart intent to the live project/service identity rather
        # than the now-gone old container ID.
        reconcile_restart_policies()
    return dict(applied=True, recovery=str(recovery), restarted=restarted,
                message='Layout saved. Original data kept. Non-running services stay stopped; use Install on a new server.')
