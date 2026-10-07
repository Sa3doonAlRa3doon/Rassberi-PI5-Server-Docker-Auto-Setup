#!/usr/bin/env python3
"""Create a root-only inventory of selected applications' bootstrap credentials.

The inventory is generated from the already-created per-app .env files. It is
never part of the public package and is deliberately a local convenience file;
the .env files remain the source of truth for Compose.
"""
from datetime import datetime, timezone
import os
from pathlib import Path


INVENTORY_NAME = 'app passwords.txt'

# These are credentials a person may use at an application's first login. The
# upstream applications do not share one password-change API, so the inventory
# records the required action without pretending to enforce it inside every
# unrelated image.
LOGIN_KEYS = {
    'ADMIN_PASSWORD', 'PORTAINER_PASSWORD', 'DOZZLE_PASSWORD',
    'BESZEL_PASSWORD', 'STIRLING_PASSWORD', 'CODE_PASSWORD',
    'FILEBROWSER_PASSWORD', 'SYNCTHING_PASSWORD', 'CALIBRE_PASSWORD',
    'FRESHRSS_PASSWORD', 'LINKDING_PASSWORD', 'CHANGEDETECTION_PASSWORD',
    'PIHOLE_PASSWORD', 'JUPYTER_TOKEN',
}

TOKEN_KEYS = {'ADMIN_TOKEN'}


def read_env(path):
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key] = value
    return values


def first_http_url(app, bind_ip):
    for port in app.get('ports', []):
        if port.get('scheme') in {'http', 'https'}:
            return f"{port['scheme']}://{bind_ip}:{port['host']}"
    return 'No browser login URL declared'


def username(app, env):
    return (env.get('BESZEL_USER_EMAIL') or env.get('ADMIN_USER') or
            'Create the first account in the application')


def credential_rows(base, manifest, bind_ip):
    """Return selected-app credential rows without printing secret values."""
    rows = []
    for app in sorted(manifest, key=lambda item: item.get('order', 50)):
        env = read_env(base / 'compose' / app['name'] / '.env')
        keys = list(app.get('secrets', []))
        if not keys:
            rows.append({
                'app': app['name'], 'url': first_http_url(app, bind_ip),
                'username': username(app, env), 'key': '', 'password': '',
                'kind': 'NO_GENERATED_PASSWORD',
                'action': 'Create the account in the application first-run screen.',
            })
            continue
        for key in keys:
            value = env.get(key, '')
            if key in LOGIN_KEYS:
                kind = 'FIRST_LOGIN_PASSWORD'
                action = ('Change this password/token during first login. If the app '
                          'has no change screen, rotate the value in its .env and restart it.')
            elif key in TOKEN_KEYS:
                kind = 'ADMIN_TOKEN'
                action = 'Use only for the private admin endpoint; replace it after initial setup if supported.'
            else:
                kind = 'INTERNAL_SECRET'
                action = 'Do not use as a web password; preserve it for the application/database.'
            rows.append({
                'app': app['name'], 'url': first_http_url(app, bind_ip),
                'username': username(app, env), 'key': key, 'password': value,
                'kind': kind, 'action': action,
            })
    return rows


def render_inventory(base, manifest, bind_ip, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    lines = [
        'Raspberry Pi application credential inventory',
        '===============================================',
        f'Generated (UTC): {generated_at}',
        '',
        'This file is root-only and is not a public package file.',
        'Each selected application has its own generated credential; there is no shared default password.',
        'Change every FIRST_LOGIN_PASSWORD entry during the first login before normal use.',
        'Credential values here are installer bootstrap values. After changing a web password in an app, update or remove the old line yourself; applications do not write new passwords back to this inventory.',
        'The per-app .env file is the source of truth. Do not paste this file into support logs or GitHub.',
        '',
    ]
    for row in credential_rows(base, manifest, bind_ip):
        lines.extend([
            f"[{row['app']}]",
            f"URL: {row['url']}",
            f"Username: {row['username']}",
            f"Credential key: {row['key'] or 'none'}",
            f"Credential: {row['password'] or 'none'}",
            f"Policy: {row['kind']}",
            f"First-login action: {row['action']}",
            '',
        ])
    return '\n'.join(lines)


def write_inventory(path, text):
    """Atomically replace a credential inventory with mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.tmp')
    flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text.rstrip() + '\n')
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
