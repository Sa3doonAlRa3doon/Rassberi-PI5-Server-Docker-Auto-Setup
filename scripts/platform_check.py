#!/usr/bin/env python3
"""Validate the Linux host family before a package installation mutates it."""
import argparse
import platform
from pathlib import Path
import shlex


SUPPORTED_IDS = {'debian', 'raspbian', 'ubuntu'}
SUPPORTED_LIKE = {'debian', 'ubuntu'}
SUPPORTED_MACHINES = {'aarch64', 'arm64'}


def os_release(path='/etc/os-release'):
    """Read the small os-release key/value format without executing it."""
    values = {}
    path = Path(path)
    if not path.is_file():
        raise RuntimeError('os-release is unavailable; this installer requires a Debian-family Linux host')
    for raw in path.read_text(encoding='utf-8').splitlines():
        if not raw or raw.lstrip().startswith('#') or '=' not in raw:
            continue
        key, value = raw.split('=', 1)
        if not key.replace('_', '').isalnum() or not key.isupper():
            continue
        try:
            tokens = shlex.split(value, posix=True)
        except ValueError as error:
            raise RuntimeError('Malformed os-release value for ' + key) from error
        values[key] = tokens[0] if tokens else ''
    if not values.get('ID'):
        raise RuntimeError('os-release does not identify this Linux distribution')
    return values


def validate(system, machine, release):
    if system.lower() != 'linux':
        raise RuntimeError('This installer requires a Linux ARM64 host.')
    if machine.lower() not in SUPPORTED_MACHINES:
        raise RuntimeError('This installer requires native ARM64 (aarch64/arm64), not ' + machine + '.')
    identifier = release.get('ID', '').lower()
    family = {item.lower() for item in release.get('ID_LIKE', '').split()}
    if identifier not in SUPPORTED_IDS and not (family & SUPPORTED_LIKE):
        raise RuntimeError('This installer supports Debian-family ARM64 hosts (Raspberry Pi OS, Debian, or Ubuntu).')
    return {'system': 'Linux', 'machine': machine.lower(), 'id': identifier,
            'id_like': sorted(family)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--os-release', default='/etc/os-release', dest='release_path')
    parser.add_argument('--system', default=platform.system())
    parser.add_argument('--machine', default=platform.machine())
    args = parser.parse_args()
    result = validate(args.system, args.machine, os_release(args.release_path))
    print('PASS: supported Linux ARM64 host: ' + result['id'])


if __name__ == '__main__':
    main()
