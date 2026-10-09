#!/usr/bin/env python3
"""Central read-first storage identity and placement checks. Never format or repair."""
import argparse
import json
import os
import posixpath
import re
from pathlib import Path
import secrets
import subprocess
import sys

BASE = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = BASE / 'configs/storage.json'
DEFAULT_MANIFEST = BASE / 'manifest.json'


def load_config(config=None):
    data = config if isinstance(config, dict) else json.loads(Path(config or DEFAULT_CONFIG).read_text(encoding='utf-8'))
    devices = data.get('devices', data)
    if not isinstance(devices, dict) or 'root' not in devices or devices['root']['mount'] != '/':
        raise RuntimeError('Storage configuration must identify the OS root filesystem')
    mounts = set()
    for key, drive in devices.items():
        target = drive.get('mount', '')
        if not re.fullmatch(r'[a-z][a-z0-9_-]*', key) or not re.fullmatch(r'/[A-Za-z0-9_./-]*', target):
            raise RuntimeError('Invalid device key or mount path: ' + str(key))
        if posixpath.normpath(target) != target or target in mounts or drive.get('filesystem') != 'ext4':
            raise RuntimeError('Unsupported or duplicate storage mount: ' + target)
        if not drive.get('uuid') and not (key == 'root' and drive.get('device')):
            raise RuntimeError('A filesystem UUID is required for ' + key)
        mounts.add(target)
    return data


def device_map(config=None):
    data = load_config(config)
    return data.get('devices', data)


def selected_manifest(manifest=DEFAULT_MANIFEST, base=None):
    """Load only installed apps when the caller supplies a manifest path.

    The manifest intentionally retains every supported application so later
    selections do not lose their configuration. A custom layout, however,
    configures storage only for the apps the owner selected. Root/status checks
    must therefore not inspect a deselected app's example HDD or media path.
    Explicit manifest lists are left unchanged so a caller can deliberately
    validate one known application.
    """
    if isinstance(manifest, list):
        return manifest
    path = Path(manifest)
    apps = json.loads(path.read_text()) if path.is_file() else []
    selection_base = Path(base) if base is not None else path.parent
    if not ((selection_base / 'installed-apps.txt').is_file() or
            (selection_base / 'configs/app-selection.json').is_file()):
        return apps
    import app_selection
    installed = set(app_selection.installed_names(selection_base, apps))
    return [app for app in apps if app.get('name') in installed]


def mounted(path):
    # --mountpoint is exact: unlike --target, it cannot silently return root.
    result = subprocess.run(['findmnt', '--json', '--mountpoint', path,
        '--output', 'TARGET,SOURCE,FSTYPE,UUID,OPTIONS'], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(path + ' is NOT MOUNTED')
    return json.loads(result.stdout)['filesystems'][0]


def containing_mount(path):
    result = subprocess.run(['findmnt', '--json', '--target', path,
        '--output', 'TARGET,SOURCE,FSTYPE,UUID,OPTIONS'], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Cannot determine filesystem for ' + path)
    return json.loads(result.stdout)['filesystems'][0]


def path_key(path, config=None):
    path = str(path)
    if not path.startswith('/') or posixpath.normpath(path) != path:
        raise RuntimeError('Invalid absolute storage path: ' + path)
    devices = device_map(config)
    for key, drive in sorted(devices.items(), key=lambda item: len(item[1]['mount']), reverse=True):
        target = drive['mount']
        if target != '/' and (path == target or path.startswith(target + '/')):
            return key
    if path == '/' or path.startswith(('/srv/', '/var/lib/')):
        return 'root'
    raise RuntimeError('Unexpected storage path: ' + path)


def app_requirements(app, config=None):
    cfg = load_config(config)
    devices = device_map(cfg)
    keys = ({'root'} if cfg.get('version') == 2 else set(app.get('mounts', [])) | {'root'})
    for item in app.get('directories', []):
        keys.add(path_key(item['path'], cfg))
    if keys - set(devices):
        raise RuntimeError('Invalid app storage dependency: ' + app['name'])
    return [k for k in devices if k in keys]


def assert_path(path, config=None, must_exist=False):
    cfg = device_map(config)
    key = path_key(str(path), config)
    path = str(path)
    if os.path.realpath(path) != path:
        raise RuntimeError(path + ' contains a symlink; review before writing')
    if os.path.lexists(path) and not os.path.isdir(path):
        raise RuntimeError(path + ' must be a directory')
    if must_exist and not os.path.isdir(path):
        raise RuntimeError('Required directory missing: ' + path)
    ancestor = path
    while not os.path.exists(ancestor):
        ancestor = os.path.dirname(ancestor)
    current = containing_mount(ancestor)
    if current['target'] != cfg[key]['mount']:
        raise RuntimeError(path + ' resolves onto unexpected filesystem ' + current['target'])
    if cfg[key].get('uuid') and current.get('uuid') != cfg[key]['uuid']:
        raise RuntimeError(path + ' resolves onto an unexpected UUID')
    if 'rw' not in current.get('options', '').split(','):
        raise RuntimeError(path + ' is on a read-only filesystem')


def write_probe(path, expected_device):
    """Use an exclusive random name relative to an opened mount dir, then delete only it."""
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    name = '.pi-storage-test-' + secrets.token_hex(12)
    created = False
    try:
        if os.fstat(directory).st_dev != expected_device:
            raise RuntimeError('Mount changed before write test: ' + path)
        fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        created = True
        try:
            payload = b'Pi storage write/read check\n'
            os.write(fd, payload)
            os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            if os.read(fd, len(payload)) != payload:
                raise RuntimeError('Write/read verification failed: ' + path)
        finally:
            os.close(fd)
    finally:
        if created:
            os.unlink(name, dir_fd=directory)
        os.close(directory)


def inspect_storage(required=None, minimum=False, manifest=DEFAULT_MANIFEST,
                    write_test=False, require_dirs=False, config=None):
    cfg = device_map(config)
    keys = required if required is not None else list(cfg)
    if set(keys) - set(cfg):
        raise RuntimeError('Unconfigured storage: ' + ', '.join(sorted(set(keys) - set(cfg))))
    apps = selected_manifest(manifest)
    paths = {key: [] for key in cfg}
    paths['root'] = ['/srv/docker', '/var/lib/docker', '/var/lib/containerd']
    for app in apps:
        for item in app.get('directories', []):
            paths[path_key(item['path'], config)].append(item['path'])
    rows = []
    for key in keys:
        expected = cfg[key]
        path = expected['mount']
        row = dict(key=key, path=path, status='OK', identity_valid=False, errors=[], warnings=[],
                   expected_uuid=expected.get('uuid'), total_bytes=None, used_bytes=None,
                   free_bytes=None, used_pct=None, directories_missing=[])
        try:
            entry = mounted(path)
            row.update(source=entry['source'], uuid=entry.get('uuid'), filesystem=entry['fstype'], options=entry['options'])
            if entry['target'] != path:
                raise RuntimeError(path + ' is NOT MOUNTED at its expected target')
            if entry['fstype'] != expected['filesystem']:
                raise RuntimeError(path + ' has unexpected filesystem type ' + entry['fstype'])
            if expected.get('uuid') and entry.get('uuid') != expected['uuid']:
                raise RuntimeError(path + ' has the WRONG UUID: ' + str(entry.get('uuid')))
            if key == 'root' and expected.get('device') and os.path.realpath(entry['source']) != expected['device']:
                raise RuntimeError('Root must be the NVMe partition ' + expected['device'])
            device = os.stat(path).st_dev
            if key != 'root' and device == os.stat('/').st_dev:
                raise RuntimeError(path + ' resolves to the NVMe root filesystem')
            row['identity_valid'] = True
            if 'rw' not in entry['options'].split(','):
                raise RuntimeError(path + ' is read-only')
            fs = os.statvfs(path)
            total = fs.f_blocks * fs.f_frsize
            free = fs.f_bavail * fs.f_frsize
            used = (fs.f_blocks - fs.f_bfree) * fs.f_frsize
            percent = 100 * used / max(used + free, 1)
            row.update(total_bytes=total, used_bytes=used, free_bytes=free, used_pct=round(percent, 2))
            if percent >= 95: row['status'] = 'EMERGENCY'
            elif percent >= 90: row['status'] = 'CRITICAL'
            elif percent >= 80: row['status'] = 'WARNING'
            elif percent >= 70: row['status'] = 'INFO'
            reserve = (40 if key == 'root' and minimum else 2) * 1024**3
            if free < reserve or percent >= 90:
                row['errors'].append(f'{path}: low space ({free/1024**3:.1f} GiB available, {percent:.1f}% used)')
                if row['status'] not in {'CRITICAL', 'EMERGENCY'}: row['status'] = 'CRITICAL'
            elif percent >= 80:
                row['warnings'].append(f'{path}: {percent:.1f}% used')
            for item in sorted(set(paths[key])):
                try:
                    assert_path(item, cfg)
                    if not os.path.isdir(item):
                        row['directories_missing'].append(item)
                        if require_dirs: row['errors'].append('Required directory missing: ' + item)
                except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                    row['errors'].append(str(exc))
            if write_test and not row['errors']:
                write_probe(path, device)
                row['write_test'] = 'PASS'
            elif write_test:
                row['write_test'] = 'SKIPPED - unsafe storage'
        except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            row['errors'].append(str(exc))
        if row['errors'] and row['status'] not in {'CRITICAL', 'EMERGENCY'}:
            row['status'] = 'ERROR'
        rows.append(row)
    return rows


def check(required=None, minimum=False, manifest=DEFAULT_MANIFEST, write_test=False,
          require_dirs=False, config=None):
    rows = inspect_storage(required, minimum, manifest, write_test, require_dirs, config)
    errors = [error for row in rows for error in row['errors']]
    if errors:
        raise RuntimeError('; '.join(errors))
    return rows


def print_rows(rows):
    print('RASPBERRY PI STORAGE CHECK')
    for row in rows:
        print(f"\n{row['key'].upper()} {row['path']} - {row['status']}")
        if row['identity_valid']:
            print('Filesystem: ' + row['filesystem'] + '; UUID: ' + str(row.get('uuid')))
        if row['total_bytes'] is not None:
            print(f"Total {row['total_bytes']/1024**3:.1f} GiB; used {row['used_pct']:.1f}%; free {row['free_bytes']/1024**3:.1f} GiB")
        for error in row['errors']: print('ERROR: ' + error)
        for warning in row['warnings']: print('WARNING: ' + warning)
        for directory in row['directories_missing']: print('DIRECTORY MISSING: ' + directory)
    checked = ', '.join(row['key'].upper() for row in rows) or 'NONE'
    print(('\nALL CHECKED STORAGE OK: ' + checked) if not any(r['errors'] for r in rows)
          else '\nSTORAGE UNAVAILABLE: DEPENDENT APPLICATIONS MUST STAY STOPPED')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--installation', action='store_true')
    parser.add_argument('--manifest', default=str(DEFAULT_MANIFEST))
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--app')
    parser.add_argument('--write-test', action='store_true')
    parser.add_argument('--directories', action='store_true')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--allow-degraded', action='store_true')
    args = parser.parse_args()
    manifest = selected_manifest(args.manifest)
    required = args.only
    if args.app:
        app = next((a for a in manifest if a['name'] == args.app), None)
        if not app: raise RuntimeError('Unknown application: ' + args.app)
        required = app_requirements(app, args.config)
        manifest = [app]
    rows = inspect_storage(required, args.installation, manifest, args.write_test, args.directories, args.config)
    if args.json: print(json.dumps(rows, indent=2))
    else: print_rows(rows)
    relevant = [r for r in rows if not args.allow_degraded or r['key'] == 'root']
    return 1 if any(r['errors'] for r in relevant) else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('ERROR: storage verification failed: ' + str(exc), file=sys.stderr)
        sys.exit(1)
