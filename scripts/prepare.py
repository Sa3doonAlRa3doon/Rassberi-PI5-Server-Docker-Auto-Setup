#!/usr/bin/env python3
"""Install templates without overwriting existing state; invoked only after mount checks."""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import app_selection
import app_passwords

BASE = Path('/srv/docker')
AUTO_START_APPS = ('onlyoffice', 'jupyter', 'stirling-pdf')

def write_new(path, text, mode=0o600):
    if path.exists():
        return
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def storage_state(manifest):
    """Return verified storage rows without creating anything below an unmounted drive."""
    guard_path = BASE / 'scripts' / 'storage_guard.py'
    if not guard_path.is_file():
        raise RuntimeError('storage_guard.py was not copied before preparation')
    import importlib.util
    spec = importlib.util.spec_from_file_location('pi_storage_guard', guard_path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    rows = guard.inspect_storage(manifest=manifest,
                                 config=BASE / 'configs' / 'storage.json')
    state = {row['key']: row for row in rows}
    if state['root']['errors']:
        raise RuntimeError('NVMe root storage is unsafe: ' + '; '.join(state['root']['errors']))
    return state


def storage_key(guard, path):
    return guard.path_key(str(path))


def synchronize_selection_copies(manifest):
    """Refresh missing legacy selection files from authoritative saved state.

    The JSON state is written first by the settings panel.  If the process is
    interrupted while updating its compatibility text files, preparation must
    never recreate those files using defaults because that would make an
    intentionally empty startup selection look enabled to older tools.
    """
    state = app_selection.selection_state(BASE)
    installed_path = BASE / 'installed-apps.txt'
    enabled_path = BASE / 'enabled-apps.txt'
    if state is not None:
        # Refresh both derived copies. A prior interrupted settings save (or a
        # hand edit of an old compatibility file) must not leave a reader with
        # a different selection than the atomically committed state.
        app_selection.atomic_names(installed_path, app_selection.installed_names(BASE, manifest))
        app_selection.atomic_names(enabled_path, app_selection.startup_names(BASE, manifest))
        return True
    if not installed_path.exists():
        app_selection.atomic_names(installed_path, [a['name'] for a in sorted(
            manifest, key=lambda a: a.get('order', 50))])
    write_new(enabled_path, ''.join(a['name']+'\n' for a in sorted(
        manifest, key=lambda a: a.get('order', 50))
        if a.get('default_enabled', True) and not a.get('blocked_reason')))
    return False

def main(source):
    manifest = json.loads((source / 'manifest.json').read_text())
    # The temporary setup page writes this file in the downloaded package before
    # install. Existing installations without it retain the complete manifest.
    # A fresh wizard selection lives beside the downloaded source. Existing
    # deployments retain their installed selection under /srv/docker.
    selection_base = source if ((source / 'installed-apps.txt').is_file() or
                                (source / 'configs/app-selection.json').is_file()) else BASE
    selected_names = set(app_selection.installed_names(selection_base, manifest))
    manifest = [app for app in manifest if app['name'] in selected_names]
    existed = {d['path']: Path(d['path']).exists() for app in manifest for d in app.get('directories', [])}
    for app in manifest:
        envfile = BASE / 'compose' / app['name'] / '.env'
        if envfile.exists():
            continue
        for d in app.get('directories', []):
            path = Path(d['path'])
            if str(path).startswith('/srv/docker/databases/') and path.is_dir() and any(path.iterdir()):
                raise RuntimeError(f'Existing database but missing .env for {app["name"]}; recover its credentials before installing.')
    ip = os.environ.get('BIND_IP', '')
    if not ip:
        route = json.loads(subprocess.check_output(['ip', '-j', 'route', 'get', '1.1.1.1'], text=True))
        ip = route[0].get('prefsrc', route[0].get('src', ''))
    address = ipaddress.ip_address(ip)
    private = any(address in ipaddress.ip_network(net) for net in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10'])
    if not private or address.version != 4:
        raise RuntimeError('Set BIND_IP to the Pi LAN or Tailscale IPv4 address (no wildcard/public bind).')
    local = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr'], text=True))
    if ip not in [a['local'] for i in local for a in i.get('addr_info', [])]:
        raise RuntimeError('BIND_IP is not assigned on this host: ' + ip)
    uid = int(os.environ.get('SUDO_UID', '1000')) or 1000
    gid = int(os.environ.get('SUDO_GID', '1000')) or 1000
    globals_ = dict(BIND_IP=ip, SERVER_IP=ip, TZ='Asia/Dubai', PUID=str(uid), PGID=str(gid), ADMIN_USER='saeed')
    for name in ['compose','configs','databases','appdata','backups','scripts','logs','docs','systemd']:
        (BASE/name).mkdir(mode=0o750, parents=True, exist_ok=True)
    # Copy only absent files. Existing compose, scripts and settings remain authoritative.
    if source.resolve() != BASE:
        for src in source.rglob('*'):
            rel = src.relative_to(source)
            if any(p in {'logs','__pycache__','.git','tests'} for p in rel.parts) or src.is_dir():
                continue
            target = BASE / rel
            target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            if not target.exists():
                shutil.copyfile(src, target)
                target.chmod(0o755 if src.suffix in {'.sh','.py'} else 0o600 if src.name == '.env' else 0o644)
    manifest_all = json.loads((BASE/'manifest.json').read_text())
    selected_names = set(app_selection.installed_names(BASE, manifest_all))
    manifest = [app for app in manifest_all if app['name'] in selected_names]
    state = storage_state(manifest)
    import importlib.util
    spec = importlib.util.spec_from_file_location('pi_storage_guard', BASE / 'scripts' / 'storage_guard.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    cfg = guard.load_config(BASE / 'configs/storage.json')
    standard = sorted({d['path'] for app in manifest for d in app.get('directories', [])
                       if d['path'].startswith(('/mnt/', '/media/'))})
    for path in standard:
        p = Path(path)
        key = storage_key(guard, p)
        if not state[key]['identity_valid'] or state[key]['errors']:
            print(f'WARNING: {key} is unavailable; will not create {p} on the NVMe mountpoint.', flush=True)
            continue
        guard.assert_path(str(p), cfg)
        if not p.exists():
            p.mkdir(mode=0o755)
            os.chown(p, uid, gid)
    for app in manifest:
        dest = BASE / 'compose' / app['name']
        dest.mkdir(mode=0o750, exist_ok=True)
        for d in app.get('directories', []):
            p = Path(d['path'])
            key = storage_key(guard, p)
            if key != 'root' and (not state[key]['identity_valid'] or state[key]['errors']):
                print(f'WARNING: skipping {app["name"]} directory {p}; {key} is unavailable.', flush=True)
                continue
            guard.assert_path(str(p), cfg)
            if not existed.get(str(p), False):
                p.mkdir(parents=True, exist_ok=True, mode=int(d.get('mode','0750'), 8))
                owner = str(d.get('uid',0)).replace('${PUID}', str(uid)).replace('${PGID}', str(gid)).replace('PUID',str(uid)).replace('PGID',str(gid))
                group = str(d.get('gid',0)).replace('${PUID}', str(uid)).replace('${PGID}', str(gid)).replace('PUID',str(uid)).replace('PGID',str(gid))
                os.chown(p, int(owner), int(group))
                p.chmod(int(d.get('mode','0750'), 8))
        envfile = dest / '.env'
        if not envfile.exists():
            values = {**app.get('env', {}), **globals_}
            for key in app.get('secrets', []):
                values[key] = secrets.token_hex(32)
            example = dest / '.env.example'
            if example.exists():
                for line in example.read_text().splitlines():
                    if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
                        continue
                    key, value = line.split('=', 1)
                    if key not in values:
                        values[key] = secrets.token_hex(32) if value == 'GENERATE' else value
            for key, value in list(values.items()):
                if value == 'GENERATE':
                    values[key] = secrets.token_hex(32)
            write_new(envfile, ''.join(f'{k}={v}\n' for k,v in values.items()))
        else:
            # New manifest fields are added without changing existing credentials or choices.
            existing = envfile.read_text()
            keys = {line.split('=', 1)[0] for line in existing.splitlines() if '=' in line and not line.lstrip().startswith('#')}
            missing = []
            for key, value in {**app.get('env', {}), **globals_}.items():
                if key not in keys:
                    missing.append(f'{key}={secrets.token_hex(32) if value == "GENERATE" else value}\n')
            for key in app.get('secrets', []):
                if key not in keys:
                    missing.append(f'{key}={secrets.token_hex(32)}\n')
            if missing:
                with envfile.open('a') as handle:
                    handle.write(('\n' if existing and not existing.endswith('\n') else '') + ''.join(missing))
        envfile.chmod(0o600)
    state_is_authoritative = synchronize_selection_copies(manifest_all)
    enabled_path = BASE / 'enabled-apps.txt'
    # Release 5 makes these three requested services start at boot. Apply that
    # migration once to older installations, while keeping later UI choices.
    marker = BASE / 'configs' / 'autostart-heavy-v1.done'
    if not marker.exists() and not state_is_authoritative:
        current = app_selection.read_names(enabled_path)
        current += [name for name in AUTO_START_APPS if name in selected_names and name not in current]
        app_selection.atomic_names(enabled_path, app_selection.ordered_names(current, manifest_all))
        marker.write_text('Release 5 heavy-app startup migration applied.\n', encoding='utf-8')
        marker.chmod(0o640)
    write_new(BASE/'server.env', f'BIND_IP={ip}\nTZ=Asia/Dubai\n')
    # Keep a convenient root-only inventory beside the downloaded package and
    # in the permanent deployment. It is generated from the selected apps'
    # existing .env files, so reruns preserve credentials while adding newly
    # selected applications to the inventory.
    inventory = app_passwords.render_inventory(BASE, manifest, ip)
    app_passwords.write_inventory(BASE / app_passwords.INVENTORY_NAME, inventory)
    if source.resolve() != BASE:
        try:
            app_passwords.write_inventory(source / app_passwords.INVENTORY_NAME, inventory)
        except OSError as error:
            print(f'WARNING: could not update {source / app_passwords.INVENTORY_NAME}: {error}', flush=True)
    # Regenerate only the package-owned storage group; retain all user dashboard cards.
    homepage = BASE / 'configs/homepage/services.yaml'
    try:
        groups = json.loads(homepage.read_text())
        mappings = [{'field': 'display.' + field, 'label': label, 'format': 'text'} for field, label in
                    [('status', 'Verified status'), ('total', 'Total'), ('used', 'Used'), ('free', 'Free'), ('percent', 'Used %')]]
        cards = [{drive.get('description') or key: {'description': drive['mount'], 'widget': {
            'type': 'customapi', 'url': 'http://storage-metrics:9079/v1/storage/' + key,
            'refreshInterval': 30000, 'display': 'list', 'mappings': mappings}}}
            for key, drive in guard.device_map(cfg).items()]
        groups = [group for group in groups if 'Verified storage' not in group]
        groups.insert(0, {'Verified storage': cards})
        homepage.write_text(json.dumps(groups, indent=2) + '\n')
    except (ValueError, OSError):
        print('Customized Homepage YAML preserved; update storage cards manually.')
    print('Configuration preserved/generated under /srv/docker. Secrets: compose/<app>/.env (root only).')

if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
