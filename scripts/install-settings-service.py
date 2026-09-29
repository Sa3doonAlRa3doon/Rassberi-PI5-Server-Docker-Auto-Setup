#!/usr/bin/env python3
"""Enable the private permanent panel only after the package is installed."""
import os
from pathlib import Path
import subprocess

from storage_setup import atomic_bytes

BASE = Path('/srv/docker')


def main():
    if os.geteuid() != 0 or not (BASE / 'server.env').exists():
        raise RuntimeError('Install the package first, then run with sudo')
    for name in ('pi-settings.service', 'pi-portable-backup.service', 'pi-portable-backup.timer'):
        source = BASE / 'systemd' / name
        atomic_bytes(Path('/etc/systemd/system') / name, source.read_bytes(), 0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', 'pi-settings.service'], check=True)
    print('Permanent HTTPS panel enabled on the server private address, port 8788.')


if __name__ == '__main__':
    main()
