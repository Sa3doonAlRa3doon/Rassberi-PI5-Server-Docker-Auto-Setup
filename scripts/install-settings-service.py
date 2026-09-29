#!/usr/bin/env python3
"""Enable the private permanent panel only after the package is installed."""
import os
from pathlib import Path
import subprocess
import time

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
    # systemctl can report success as soon as the service is queued.  Wait for
    # the service to create its root-only key before the next shell command
    # tries to read it.
    key = BASE / 'configs/settings-private/access-key'
    for _ in range(50):
        if key.is_file() and key.stat().st_size > 1:
            break
        state = subprocess.run(['systemctl', 'is-active', '--quiet', 'pi-settings.service'])
        if state.returncode != 0:
            raise RuntimeError('pi-settings.service did not stay active; inspect journalctl -u pi-settings.service')
        time.sleep(0.1)
    else:
        raise RuntimeError('Settings service started but did not create its access key; inspect journalctl -u pi-settings.service')
    print('Permanent HTTPS panel enabled on the server private address, port 8788.')


if __name__ == '__main__':
    main()
