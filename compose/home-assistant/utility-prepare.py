#!/usr/bin/env python3
"""Create a minimal first-run Home Assistant config without replacing user state."""
import ipaddress
import json
import os
from pathlib import Path

BASE = Path('/srv/docker')


def main():
    config = BASE / 'appdata/home-assistant/configuration.yaml'
    if config.is_symlink():
        raise RuntimeError('Refusing a symlinked Home Assistant configuration')
    if config.exists():
        return
    env = {}
    for line in (BASE / 'compose/home-assistant/.env').read_text().splitlines():
        if line and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            env[key] = value.strip().strip("\"'")
    address = str(ipaddress.IPv4Address(env['BIND_IP']))
    content = ('# Generated once. Existing configuration is never replaced.\n'
               'default_config:\n\n'
               'homeassistant:\n  time_zone: ' + json.dumps(env.get('TZ', 'Asia/Dubai')) + '\n\n'
               'http:\n  server_host: ' + json.dumps(address) + '\n  server_port: 8123\n\n'
               '# Default SQLite recorder database remains under /config on NVMe.\n'
               'recorder:\n  purge_keep_days: 7\n  commit_interval: 30\n')
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(content)


if __name__ == '__main__':
    main()
