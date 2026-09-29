#!/usr/bin/env python3
"""Idempotently register this Pi after the hub and local agent are healthy."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

BASE = Path('/srv/docker')


def request(base, endpoint, data=None, token=None):
    headers = {'Content-Type':'application/json'}
    if token:
        headers['Authorization'] = token
    req = urllib.request.Request(base + endpoint, data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def main():
    env = {}
    for line in (BASE/'compose/beszel/.env').read_text().splitlines():
        if line and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=',1)
            env[key] = value.strip().strip('\"\'')
    base = 'http://' + env['BIND_IP'] + ':8098'
    credentials = {'identity':env.get('BESZEL_USER_EMAIL','saeed@pi.local'), 'password':env['BESZEL_PASSWORD']}
    result = None
    for _ in range(10):
        try:
            result = request(base, '/api/collections/users/auth-with-password', credentials)
            break
        except (OSError, ValueError, urllib.error.URLError):
            time.sleep(2)
    if result is None:
        raise RuntimeError('Beszel is running but its saved credentials did not authenticate. Existing user credentials are preserved; add /beszel_socket/beszel.sock manually in the UI.')
    token, user = result['token'], result['record']['id']
    existing = request(base, '/api/collections/systems/records?perPage=500', token=token)
    if any(x.get('host') == '/beszel_socket/beszel.sock' for x in existing['items']):
        print('Beszel local system already registered; settings preserved.')
        return
    request(base, '/api/collections/systems/records', {'name':'Raspberry Pi','host':'/beszel_socket/beszel.sock','port':45876,'users':[user],'status':'pending','info':{}}, token)
    print('Beszel local Pi registered. Configure notification channels and alert thresholds in the UI.')


if __name__ == '__main__':
    main()
