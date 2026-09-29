#!/usr/bin/env python3
"""Resolve AUTO once to one directly connected private LAN, preserving manual scope."""
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ENV_FILE = Path('/srv/docker/compose/netalertx/.env')
PRIVATE = [ipaddress.ip_network(network) for network in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]


def local_scope(address, interfaces):
    ip = ipaddress.IPv4Address(address)
    if not any(ip in network for network in PRIVATE):
        return []
    for interface in interfaces:
        name = interface.get('ifname', '')
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+', name):
            continue
        for entry in interface.get('addr_info', []):
            if entry.get('family') != 'inet' or entry.get('local') != address:
                continue
            network = ipaddress.ip_network(f"{address}/{entry['prefixlen']}", strict=False)
            if network.prefixlen < 20 or network.prefixlen > 30:
                return []
            if not any(network.subnet_of(private) for private in PRIVATE):
                return []
            return [str(network) + ' --interface=' + name]
    return []


def main():
    if ENV_FILE.is_symlink():
        raise RuntimeError('Refusing a symlinked environment file')
    original = ENV_FILE.read_text()
    env = {}
    for line in original.splitlines():
        if line and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            env[key] = value.strip().strip("\"'")
    if env.get('NETALERTX_SCAN_SUBNETS') != 'AUTO':
        return
    interfaces = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr'], text=True))
    scope = local_scope(env['BIND_IP'], interfaces)
    value = repr(scope)
    content = '\n'.join('NETALERTX_SCAN_SUBNETS=' + value if line.startswith('NETALERTX_SCAN_SUBNETS=') else line for line in original.splitlines()) + '\n'
    fd, name = tempfile.mkstemp(prefix='.netalertx-env-', dir=ENV_FILE.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, ENV_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    if scope:
        print('NetAlertX local discovery scope: ' + scope[0])
    else:
        print('NetAlertX discovery remains disabled. Set NETALERTX_SCAN_SUBNETS to your own local LAN and interface before enabling scans.')


if __name__ == '__main__':
    main()
