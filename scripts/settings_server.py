#!/usr/bin/env python3
"""Small authenticated HTTPS setup/settings service; Python standard library only."""
import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import threading
import time
from urllib.parse import urlsplit

import storage_setup as layout
import app_selection

BASE = Path(__file__).resolve().parents[1]
WEB = BASE / 'configs/settings-ui'
STORAGE_PREFERENCES = Path('configs/storage-preferences.json')
STATE = dict(running=False, name=None, result=None, error=None)
JOB_LOCK = threading.Lock()
LAST_ACCESS = time.monotonic()
DEMO = False


def deployed():
    return BASE.resolve() == Path('/srv/docker')


def private_ipv4(value):
    address = ipaddress.ip_address(value)
    return address.version == 4 and any(address in ipaddress.ip_network(net) for net in
        ('127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10'))


def configured_ip():
    requested = os.environ.get('BIND_IP', '').strip()
    if requested:
        return requested
    path = BASE / 'server.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith('BIND_IP='):
                return line.split('=', 1)[1]
    route = json.loads(subprocess.check_output(['ip', '-j', 'route', 'get', '1.1.1.1'], text=True))
    return route[0].get('prefsrc', route[0].get('src', ''))


def selected_apps():
    manifest = layout.read_json(BASE / 'manifest.json')
    # An empty enabled-apps.txt is a deliberate "start nothing at boot" choice.
    # Only installations that predate the startup-selection file receive the
    # legacy default-enabled fallback.
    if ((BASE / 'enabled-apps.txt').is_file() or
            (BASE / app_selection.STATE_FILE).is_file()):
        return app_selection.startup_names(BASE, manifest)
    return [a['name'] for a in manifest if a.get('default_enabled', True) and
            a['name'] in app_selection.installed_names(BASE, manifest)]


def installed_apps():
    manifest = layout.read_json(BASE / 'manifest.json')
    # A downloaded package has no implicit app set.  Keeping this empty until
    # the owner saves a selection prevents the storage table from presenting
    # the supplied example profile as if every app were already chosen.
    if not deployed() and not ((BASE / 'installed-apps.txt').is_file() or
                               (BASE / app_selection.STATE_FILE).is_file()):
        return []
    return app_selection.installed_names(BASE, manifest)


def storage_preferences():
    return layout.read_json(BASE / STORAGE_PREFERENCES, {
        'version': 1, 'system_uuid': '', 'bulk_uuid': '', 'media_uuid': ''})


def app_storage_class(app):
    classes = ['SSD / NVMe']
    paths = [d.get('path', '') for d in app.get('directories', [])]
    database = app.get('database') or {}
    if database.get('path'):
        paths.append(database['path'])
    mounts = set(app.get('mounts', []))
    if 'hdd' in mounts or any(p.startswith('/mnt/hdd/') for p in paths):
        classes.append('HDD / bulk files')
    if 'media' in mounts or any(p.startswith('/mnt/media/') for p in paths):
        classes.append('microSD / media')
    return ' + '.join(dict.fromkeys(classes))


def app_storage_estimate(app):
    """Explain the pre-pull disk estimate without downloading an image."""
    paths = [d.get('path', '') for d in app.get('directories', [])]
    if (app.get('database') or {}).get('path'):
        paths.append(app['database']['path'])
    if not paths:
        return 'No persistent server data; image size is shown after install'
    if any(p.startswith('/mnt/') for p in paths):
        return 'Data-dependent bulk storage; image size is shown after install'
    return 'Appdata/config only; image size is shown after install'


def snapshot():
    manifest = layout.read_json(BASE / 'manifest.json')
    disks = layout.discover() if not DEMO else [
        dict(name='/dev/nvme0n1p2', uuid='demo-ssd', mount='/', eligible=True, kind='SSD',
             model='512 GB NVMe SSD (preview)', size=512*1024**3, free_bytes=380*1024**3),
        dict(name='/dev/sdb1', uuid='demo-hdd', mount='/mnt/hdd', eligible=True, kind='HDD',
             model='1 TB Seagate HDD (preview)', size=1000*1024**3, free_bytes=780*1024**3),
        dict(name='/dev/mmcblk0p1', uuid='demo-media', mount='/mnt/media', eligible=True, kind='microSD',
             model='256 GB microSD (preview)', size=256*1024**3, free_bytes=210*1024**3)]
    installed = installed_apps()
    placements = layout.catalog(BASE, installed)
    paths_by_app = {a['name']: [] for a in manifest}
    for row in placements:
        for name in row.get('apps', []):
            paths_by_app.setdefault(name, []).append({'kind': row['kind'], 'path': row['current']})
    apps = []
    for app in manifest:
        declared = []
        for directory in app.get('directories', []):
            declared.append({'kind': 'bulk' if directory.get('path', '').startswith('/mnt/') else 'appdata',
                             'path': directory.get('path', '')})
        if (app.get('database') or {}).get('path'):
            declared.append({'kind': 'database', 'path': app['database']['path']})
        apps.append({**{k: app.get(k) for k in ('name', 'memory_mib', 'default_enabled', 'setup', 'ports', 'optional', 'blocked_reason')},
            'description': app.get('description') or app.get('setup') or 'Managed by the Pi server package.',
            'storage_class': app_storage_class(app),
            'storage_estimate': app_storage_estimate(app),
            'storage_paths': paths_by_app.get(app['name']) or declared,
            'installed': app['name'] in installed,
            # A selected app becomes startable after Install package has
            # created its guarded directories and private environment.
            'prepared': (BASE / 'compose' / app['name'] / '.env').is_file()})
    selection_saved = ((BASE / 'installed-apps.txt').is_file() or
                       (BASE / app_selection.STATE_FILE).is_file())
    layout_saved = (BASE / 'configs/layout.json').is_file()
    return dict(disks=disks, placements=placements, enabled=selected_apps(), installed=installed,
        apps=apps, storage_preferences=storage_preferences(), selection_saved=selection_saved,
        layout_saved=layout_saved, fresh_setup=not deployed() and not selection_saved,
        backup=layout.read_json(BASE / 'configs/portable-backup.json', dict(mount='/mnt/backup', uuid='', folder='pi-server', include_bulk=True)),
        demo=DEMO, deployed=deployed(), job=STATE.copy())


def external(args, timeout=7200):
    """Full logs stay local and private; never return command output containing secrets."""
    log = BASE / 'logs/settings-operations.log'
    log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'a') as file:
        result = subprocess.run(args, stdout=file, stderr=subprocess.STDOUT, timeout=timeout,
                                env={**os.environ, 'BIND_IP': configured_ip()})
    if result.returncode:
        raise RuntimeError('Operation returned ' + str(result.returncode) + '; inspect private log ' + str(log))
    return {'completed': True, 'log': str(log)}


def with_lock(callback):
    import fcntl
    with open('/run/lock/pi-server.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another install, backup or storage operation is running')
        return callback()


def backup_command(action, data):
    command = ['python3', str(BASE / 'scripts/portable-backup.py'), action,
               '--config', str(BASE / 'configs/portable-backup.json'), '--json']
    if data.get('backup'):
        if not isinstance(data['backup'], str) or not __import__('re').fullmatch(r'[A-Za-z0-9_.-]+', data['backup']):
            raise ValueError('Invalid snapshot name')
        command += ['--backup', data['backup']]
    # The backup script reports JSON; no env/secrets returned.
    result = subprocess.run(command, capture_output=True, text=True, timeout=7200)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-3000:])
    return json.loads(result.stdout)


def save_backup(data):
    disks = layout.discover()
    uuid = data.get('uuid', '')
    if not uuid:
        raise ValueError('Select the mounted future backup drive after attaching it')
    disk = next((d for d in disks if d.get('uuid') == uuid and d.get('eligible')), None)
    if not disk or disk['mount'] == '/':
        raise ValueError('Select a separately mounted ext4 backup drive')
    devices = layout.guard.device_map(BASE / 'configs/storage.json')
    sources = {d.get('uuid') for d in devices.values()}
    source_disks = {d.get('physical') for d in disks if d.get('uuid') in sources}
    if uuid in sources or disk.get('physical') in source_disks:
        raise ValueError('Backup must be a different physical disk from all active source storage')
    folder = data.get('folder', 'pi-server')
    if not __import__('re').fullmatch(r'[A-Za-z0-9_-]+', folder):
        raise ValueError('Backup folder must be a single plain name')
    config = dict(mount=disk['mount'], uuid=uuid, folder=folder, include_bulk=bool(data.get('include_bulk', True)), daily=bool(data.get('daily')))
    layout.atomic_json(BASE / 'configs/portable-backup.json', config)
    if deployed():
        external(['systemctl', 'enable' if data.get('daily') else 'disable', '--now', 'pi-portable-backup.timer'])
    return {'saved': True, 'daily': bool(data.get('daily')), 'config': config}


def dispatch(action, data):
    if DEMO:
        raise ValueError('Preview is read-only. Run the setup wizard on your Pi to apply changes.')
    if action == 'layout-apply':
        return with_lock(lambda: layout.apply(data.get('placements'), bool(data.get('migrate'))))
    if action == 'save-storage-preferences':
        values = data if isinstance(data, dict) else {}
        requested = {key: values.get(key, '') for key in ('system_uuid', 'bulk_uuid', 'media_uuid')}
        if not requested['system_uuid'] or not all(isinstance(value, str) for value in requested.values()):
            raise ValueError('Choose a primary SSD before continuing')
        def save_preferences():
            disks = layout.discover()
            eligible = {d.get('uuid'): d for d in disks if d.get('eligible')}
            for key, uuid in requested.items():
                if uuid and uuid not in eligible:
                    raise ValueError('Selected storage is not mounted and writable: ' + key)
            if eligible[requested['system_uuid']].get('kind') != 'SSD':
                raise ValueError('Primary application and database storage must be an SSD/NVMe filesystem')
            config = {'version': 1, **requested}
            layout.atomic_json(BASE / STORAGE_PREFERENCES, config)
            return {'saved': True, 'preferences': config}
        return with_lock(save_preferences)
    if action == 'install':
        if not deployed():
            missing = []
            if not (BASE / 'configs' / 'app-selection.json').is_file() and not (BASE / 'installed-apps.txt').is_file():
                missing.append('save your application selection')
            if not (BASE / 'configs' / 'layout.json').is_file():
                missing.append('apply the reviewed storage layout')
            if missing:
                raise ValueError('Before installing, ' + ' and '.join(missing) + '. No Docker images have been pulled.')
        return external(['bash', str(BASE / 'install-all.sh')])
    if action == 'save-apps':
        manifest = layout.read_json(BASE / 'manifest.json')
        installed = data.get('installed', [])
        startup = data.get('enabled', [])
        if (not isinstance(installed, list) or not all(isinstance(n, str) for n in installed) or
                not isinstance(startup, list) or not all(isinstance(n, str) for n in startup)):
            raise ValueError('Application selections must be lists of names')
        before = set(installed_apps())
        planned_installed = app_selection.ordered_names(installed, manifest)
        if not planned_installed:
            raise ValueError('Select at least one application to install')
        planned_startup = app_selection.ordered_names(startup, manifest)
        if not set(planned_startup).issubset(planned_installed):
            raise ValueError('Every application selected for startup must also be selected for installation')
        order = {app['name']: app.get('order', 50) for app in manifest}
        removed = sorted(before - set(planned_installed), key=lambda name: order[name], reverse=True)
        def save():
            stopped = []
            if deployed():
                # Keep the existing authoritative selection until every
                # removed stack has stopped. A stop failure must leave the
                # old app in storage-watch/guard scope rather than creating
                # an untracked writer on a later-missing drive.
                for name in removed:
                    external(['python3', str(BASE / 'scripts' / 'manage.py'), 'stop', name])
                    stopped.append(name)
            result = app_selection.save_selection(BASE, manifest, planned_installed, planned_startup)
            result['stopped'] = stopped
            return result
        return with_lock(save)
    if action in {'app-start', 'app-stop'}:
        name = data.get('app')
        if name not in {a['name'] for a in layout.read_json(BASE / 'manifest.json')}:
            raise ValueError('Unknown application')
        if not deployed():
            raise ValueError('Install the package first')
        return external(['bash', str(BASE / ('start-all.sh' if action == 'app-start' else 'stop-all.sh')), name])
    if action == 'save-backup':
        return with_lock(lambda: save_backup(data))
    if action in {'backup-create', 'backup-verify', 'backup-plan'}:
        return backup_command(action.split('-', 1)[1], data)
    if action == 'tailscale-configure':
        return external(['python3', str(BASE / 'scripts/setup-tailscale-homepage.py'), '--apply'])
    if action == 'enable-panel':
        return external(['python3', str(BASE / 'scripts/install-settings-service.py')])
    raise ValueError('Unknown operation')


def start_job(action, data):
    if not JOB_LOCK.acquire(blocking=False):
        raise RuntimeError('An operation is already running. Wait for its result.')
    STATE.update(running=True, name=action, result=None, error=None)
    def worker():
        try:
            STATE['result'] = dispatch(action, data)
        except Exception as exc:
            STATE['error'] = str(exc)
        finally:
            STATE['running'] = False
            JOB_LOCK.release()
    threading.Thread(target=worker, daemon=True).start()
    return STATE.copy()


class Handler(BaseHTTPRequestHandler):
    server_version = 'PiSettings'

    def log_message(self, *_):
        pass

    def reply(self, code, body, content_type='application/json'):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def authorized(self):
        global LAST_ACCESS
        if self.headers.get('Host') not in self.server.allowed_hosts:
            self.reply(403, {'error': 'Unrecognized host'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin != self.server.origin:
            self.reply(403, {'error': 'Cross-origin request refused'})
            return False
        supplied = self.headers.get('Authorization', '').removeprefix('Bearer ')
        if not hmac.compare_digest(supplied, self.server.token):
            time.sleep(0.15)
            self.reply(401, {'error': 'Enter the access key printed in your Pi terminal'})
            return False
        LAST_ACCESS = time.monotonic()
        return True

    def do_GET(self):
        try:
            path = urlsplit(self.path).path
            if path.startswith('/api/'):
                if not self.authorized():
                    return
                if path == '/api/state':
                    return self.reply(200, snapshot())
                if path == '/api/job':
                    return self.reply(200, STATE.copy())
                return self.reply(404, {'error': 'Unknown endpoint'})
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8'),
                     '/navigation.css': ('navigation.css', 'text/css; charset=utf-8')}
            if path not in files:
                return self.reply(404, {'error': 'Not found'})
            filename, content_type = files[path]
            self.reply(200, (WEB / filename).read_bytes(), content_type)
        except Exception as exc:
            self.reply(400, {'error': str(exc)})

    def do_POST(self):
        if not self.authorized():
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 2 or length > 131072 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.reply(400, {'error': 'Expected a small JSON request'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object')
            action = urlsplit(self.path).path.removeprefix('/api/')
            if action == 'auto-select':
                state = snapshot()
                return self.reply(200, {'placements': layout.auto_select(state['disks'], state['placements'], state['backup'].get('uuid'), state['storage_preferences'])})
            if action == 'layout-plan':
                if DEMO:
                    raise ValueError('Preview is read-only; live mount checks run on your Pi')
                return self.reply(200, layout.plan(data.get('placements')))
            if action == 'finish':
                if STATE['running']:
                    raise RuntimeError('Wait for the current operation before closing setup')
                if not self.server.temporary:
                    raise ValueError('This is the permanent panel; close your browser to leave it')
                self.reply(200, {'closed': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self.reply(202, start_job(action, data))
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
            self.reply(400, {'error': str(exc)})


def credentials(bind):
    private = BASE / 'configs/settings-private'
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    private.chmod(0o700)
    tokenfile = private / 'access-key'
    if not tokenfile.exists():
        layout.atomic_bytes(tokenfile, (secrets.token_urlsafe(36) + '\n').encode())
    key, cert = private / 'tls.key', private / 'tls.crt'
    # Stable private certificate can include only the address present at creation.
    if not cert.exists() or not key.exists():
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-sha256', '-nodes',
            '-days', '825', '-keyout', str(key), '-out', str(cert), '-subj', '/CN=Pi Server Settings',
            '-addext', 'subjectAltName=IP:' + bind], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        cert.chmod(0o600)
    return tokenfile.read_text().strip(), key, cert


def main():
    global DEMO
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()
    DEMO = args.demo
    bind = args.bind or ('127.0.0.1' if DEMO else configured_ip())
    if not private_ipv4(bind) or not 1024 <= args.port <= 65535:
        raise SystemExit('Bind to one private IPv4 address on a port from 1024 to 65535')
    if DEMO:
        if bind != '127.0.0.1':
            raise SystemExit('Preview can bind only to 127.0.0.1')
        token, key, cert = 'preview-only', None, None
    else:
        if os.geteuid() != 0 or __import__('platform').system() != 'Linux':
            raise SystemExit('Run on Linux with sudo')
        local = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr'], text=True))
        if bind not in [a['local'] for i in local for a in i.get('addr_info', [])]:
            raise SystemExit('Bind address is not assigned to this machine')
        token, key, cert = credentials(bind)
    server = ThreadingHTTPServer((bind, args.port), Handler)
    server.token = token
    server.temporary = args.setup or DEMO
    server.allowed_hosts = {f'{bind}:{args.port}'}
    server.origin = ('http' if DEMO else 'https') + f'://{bind}:{args.port}'
    if not DEMO:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print('Open ' + server.origin, flush=True)
    # Never print the key into the permanent service's journal.
    if server.temporary:
        print('Access key: ' + token, flush=True)
    else:
        print('Read the access key with sudo cat /srv/docker/configs/settings-private/access-key', flush=True)
    if cert:
        der = ssl.PEM_cert_to_DER_cert(cert.read_text())
        print('Self-signed certificate SHA256: ' + hashlib.sha256(der).hexdigest(), flush=True)
    def expiry():
        while server.temporary:
            time.sleep(15)
            if not STATE['running'] and time.monotonic() - LAST_ACCESS > 7200:
                server.shutdown()
                return
    threading.Thread(target=expiry, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
