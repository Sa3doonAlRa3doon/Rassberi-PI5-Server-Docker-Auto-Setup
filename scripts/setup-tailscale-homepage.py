#!/usr/bin/env python3
"""Review or apply private Tailscale dashboard routes. Never enables Funnel."""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

BASE = Path('/srv/docker')
EXCLUDED = {'homepage', 'homepage-tailscale', 'docker-socket-proxy', 'autoheal', 'diun'}


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(' '.join(args[:3]) + ': ' + result.stderr.strip())
    return result.stdout


def read_env(path):
    values = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            if line and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key] = value.strip().strip('\"\'')
    return values


def atomic(path, text, mode=0o600, owner=None):
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise RuntimeError('Refusing symlinked configuration: ' + str(path))
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(tmp, mode)
        if owner:
            os.chown(tmp, *owner)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def identity():
    status = json.loads(command(['tailscale', 'status', '--json']))
    if status.get('BackendState') != 'Running':
        raise RuntimeError('Log this Pi into Tailscale before configuring the second Homepage.')
    ips = [ip for ip in status.get('TailscaleIPs', []) if ':' not in ip]
    if len(ips) != 1 or ipaddress.ip_address(ips[0]) not in ipaddress.ip_network('100.64.0.0/10'):
        raise RuntimeError('Tailscale did not report exactly one valid tailnet IPv4 address.')
    host = status.get('Self', {}).get('DNSName', '').rstrip('.')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]+\.ts\.net', host):
        raise RuntimeError('Enable MagicDNS: a valid device.ts.net hostname is required.')
    local = json.loads(command(['ip', '-j', '-4', 'addr']))
    assigned = {a['local'] for item in local for a in item.get('addr_info', [])}
    if ips[0] not in assigned:
        raise RuntimeError('Tailscale IPv4 is not assigned on the host; userspace networking is unsupported.')
    version = command(['tailscale', 'version']).splitlines()[0]
    match = re.match(r'(\d+)\.(\d+)\.(\d+)', version)
    if not match or tuple(map(int, match.groups())) < (1, 92, 0):
        raise RuntimeError('Private forwarding to LAN-bound applications requires Tailscale 1.92.0 or later.')
    return {'ipv4': ips[0], 'hostname': host, 'version': version, 'local_ipv4': sorted(assigned)}


def routes(manifest, info, base=BASE):
    output = [{'app': 'homepage-tailscale', 'port': 443,
               'target': 'http://' + info['ipv4'] + ':3003',
               'url': 'https://' + info['hostname'] + '/'}]
    seen = {443}
    for app in sorted(manifest, key=lambda a: (a.get('order', 50), a['name'])):
        if app['name'] in EXCLUDED or app.get('blocked_reason'):
            continue
        env = read_env(base / 'compose' / app['name'] / '.env')
        bind = env.get('BIND_IP', '')
        if not bind or bind not in info['local_ipv4']:
            continue
        for port in app.get('ports', []):
            if port.get('protocol', 'tcp') != 'tcp' or port.get('scheme') not in {'http', 'https'}:
                continue
            number = int(port['host'])
            remote = number + 10000
            if remote > 65535 or remote in seen:
                raise RuntimeError('Ambiguous tailnet port for ' + app['name'])
            seen.add(remote)
            scheme = 'https+insecure' if port['scheme'] == 'https' else 'http'
            output.append({'app': app['name'], 'port': remote,
                           'target': f'{scheme}://{bind}:{number}',
                           'url': f'https://{info["hostname"]}:{remote}/'})
            break
    return output


def conflict(config, route, hostname):
    """Only an identical, private root handler is reusable. Preserve all other state."""
    port = str(route['port'])
    key = hostname + ':' + port
    for fg in (config.get('Foreground') or {}).values():
        if port in (fg.get('TCP') or {}):
            return 'Port is used by a foreground Tailscale Serve session'
    if (config.get('AllowFunnel') or {}).get(key):
        return 'Port is already public via Funnel; review it manually'
    tcp = (config.get('TCP') or {}).get(port)
    web = (config.get('Web') or {}).get(key)
    if tcp is None and web is None:
        return None
    if tcp != {'HTTPS': True} or web != {'Handlers': {'/': {'Proxy': route['target']}}}:
        return 'Existing Serve configuration differs; it will not be overwritten'
    return None


def services_yaml(entries):
    cards = [{item['app'].replace('-', ' ').title(): {
        'href': item['url'], 'description': 'Private Tailscale connection; app login still required',
        'icon': item['app'] + '.png'}} for item in entries if item['app'] != 'homepage-tailscale']
    return json.dumps([{'Private server apps': cards}], indent=2) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true')
    group.add_argument('--dry-run', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if os.name != 'posix':
        raise RuntimeError('Run this helper on the Raspberry Pi, not Windows.')
    info = identity()
    manifest = json.loads((BASE / 'manifest.json').read_text())
    entries = routes(manifest, info)
    before = json.loads(command(['tailscale', 'serve', 'status', '--json']) or '{}')
    errors = [dict(app=r['app'], error=reason) for r in entries
              if (reason := conflict(before, r, info['hostname']))]
    plan = {'ready': not errors, 'identity': info, 'dashboard': 'http://' + info['ipv4'] + ':3003/',
            'https_dashboard': entries[0]['url'], 'routes': entries, 'errors': errors,
            'commands': [['tailscale', 'serve', '--bg', '--https=' + str(r['port']), r['target']] for r in entries],
            'notice': 'Private Serve only. App trusted domains/origins may need the generated HTTPS URL; see TAILSCALE-HOMEPAGE.md.'}
    if errors or not args.apply:
        print(json.dumps(plan, indent=2))
        return 1 if errors else 0
    if os.geteuid() != 0:
        raise RuntimeError('Use sudo to apply the reviewed plan.')
    import fcntl
    with open('/run/lock/pi-server.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        command([sys.executable, str(BASE / 'scripts/storage_guard.py'), '--app', 'homepage-tailscale', '--directories'])
        project = BASE / 'compose/homepage-tailscale'
        envfile = project / '.env'
        values = read_env(envfile)
        values.update(TAILSCALE_IPV4=info['ipv4'], TAILSCALE_HOSTNAME=info['hostname'])
        current = json.loads(command(['tailscale', 'serve', 'status', '--json']) or '{}')
        if current != before:
            raise RuntimeError('Tailscale Serve changed during review; rerun the helper.')
        created = []
        try:
            for entry, cmd in zip(entries, plan['commands']):
                if str(entry['port']) in (before.get('TCP') or {}):
                    continue
                command(cmd)
                created.append(entry)
            after = json.loads(command(['tailscale', 'serve', 'status', '--json']) or '{}')
            if any(str(r['port']) not in (after.get('TCP') or {}) or
                   conflict(after, r, info['hostname']) for r in entries):
                raise RuntimeError('Tailscale did not retain the requested private routes.')
            atomic(envfile, ''.join(f'{k}={v}\n' for k, v in values.items()))
            owner = (int(values.get('PUID', 1000)), int(values.get('PGID', 1000)))
            cfg = BASE / 'configs/homepage-tailscale'
            old_services = cfg / 'services.yaml'
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            if old_services.exists():
                atomic(cfg / ('services-before-' + stamp + '.json'), old_services.read_text(), 0o600)
            atomic(old_services, services_yaml(entries), 0o640, owner)
            atomic(cfg / 'routes.json', json.dumps(plan, indent=2) + '\n', 0o640, owner)
        except BaseException:
            for entry in reversed(created):
                subprocess.run(['tailscale', 'serve', '--https=' + str(entry['port']), '--set-path=/', 'off'],
                               capture_output=True, timeout=30)
            raise
    plan['applied'] = True
    plan['next'] = 'sudo /srv/docker/start-all.sh homepage-tailscale'
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'ready': False, 'error': str(error)}))
        raise SystemExit(1)
