#!/usr/bin/env python3
"""Atomic host configuration; only the verified HDD entry may change in fstab."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

BASE = Path('/srv/docker')


def digest(content):
    return hashlib.sha256(content).hexdigest()


def fstab_candidate(original, storage):
    """Preserve every byte outside the single HDD line; never change OS/media rows."""
    hdd = storage['hdd']
    target, uuid = hdd['mount'], hdd['uuid']
    lines = original.splitlines(keepends=True)
    rows = [(i, line.split('#', 1)[0].split()) for i, line in enumerate(lines)]
    rows = [(i, fields) for i, fields in rows if fields]
    for _, fields in rows:
        if len(fields) < 4:
            raise RuntimeError('Malformed existing fstab entry; review before migration.')
    for mount in ('/', target, storage['media']['mount']):
        if sum(fields[1] == mount for _, fields in rows) > 1:
            raise RuntimeError('Duplicate fstab mount point: ' + mount)
    if any(fields[0] == 'UUID=' + uuid and fields[1] != target for _, fields in rows):
        raise RuntimeError('New HDD UUID is already configured at another fstab target.')
    matches = [(i, fields) for i, fields in rows if fields[1] == target]
    replacement = f'UUID={uuid} {target} {hdd["filesystem"]} defaults,nofail 0 2\n'
    if matches:
        i, fields = matches[0]
        if fields[2] != 'ext4' or not (fields[0].startswith('UUID=') or fields[0].startswith('/dev/')):
            raise RuntimeError('Unexpected existing HDD fstab source/type; manual review required.')
        if '#' in lines[i]:
            replacement = replacement.rstrip('\n') + ' #' + lines[i].split('#', 1)[1].rstrip('\r\n') + '\n'
        lines[i] = replacement
    else:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.append(replacement)
    return ''.join(lines)


def validate_fstab(content):
    with tempfile.NamedTemporaryFile(mode='w', prefix='pi-fstab-', encoding='utf-8') as file:
        file.write(content)
        file.flush()
        result = subprocess.run(['findmnt', '--verify', '--tab-file', file.name], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Candidate fstab validation failed: ' + result.stdout + result.stderr)


def atomic_write(path, content, backup_dir=None, mode=None):
    path = Path(path)
    if path.resolve() != path.absolute():
        raise RuntimeError('Refusing symlinked managed target: ' + str(path))
    existed = path.exists()
    previous = path.read_bytes() if existed else None
    if previous == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if existed and backup_dir:
        saved = Path(backup_dir) / str(path).lstrip('/')
        saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(path, saved)
    metadata = path.stat() if existed else None
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, mode if mode is not None else metadata.st_mode & 0o777 if metadata else 0o644)
        if metadata:
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def managed_files(base=BASE):
    mapping = {'/etc/systemd/system/docker.service.d/20-pi-storage.conf': 'systemd/docker-storage.conf'}
    for name in ('pi-storage-watch.service', 'pi-storage-watch.timer', 'pi-storage-start.service',
                 'pi-storage-metrics.service', 'pi-storage-metrics.timer',
                 'pi-portable-backup.service', 'pi-portable-backup.timer'):
        mapping['/etc/systemd/system/' + name] = 'systemd/' + name
    return mapping


def plan_host_files(base=BASE, accepted_old=None):
    accepted_old = accepted_old or {}
    result = {}
    for destination, relative in managed_files(base).items():
        source = base / relative
        if not source.is_file():
            raise RuntimeError('Missing managed systemd template: ' + str(source))
        target = Path(destination)
        content = source.read_bytes()
        if target.exists() and target.read_bytes() != content:
            if digest(target.read_bytes()) not in accepted_old.get(destination, set()):
                raise RuntimeError('Customized managed host file requires review: ' + destination + '; use apply-storage-update.sh for the known previous release.')
        result[destination] = content
    return result


def check_hdd(base=BASE, write_test=True):
    command = ['python3', str(base / 'scripts/storage_guard.py'), '--only', 'root', 'hdd',
               '--config', str(base / 'configs/storage.json'), '--manifest', str(BASE / 'manifest.json')]
    if write_test:
        command.append('--write-test')
    return subprocess.run(command).returncode == 0


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo.')
    storage = json.loads((BASE / 'configs/storage.json').read_text())
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backups = BASE / 'backups' / ('host-config-' + stamp)
    planned = plan_host_files()
    if storage.get('version') == 2:
        print('Custom layout selected; existing OS and data fstab entries are preserved. Configure persistent UUID mounts before reboot.')
    elif check_hdd():
        original = Path('/etc/fstab').read_text()
        candidate = fstab_candidate(original, storage)
        validate_fstab(candidate)
        planned['/etc/fstab'] = candidate.encode()
    else:
        print('WARNING: HDD unavailable/unsafe; its fstab entry is unchanged. Unrelated services may continue.')
    planned['/etc/apt/apt.conf.d/52pi-server-security'] = (
        'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n'
        'Unattended-Upgrade::Automatic-Reboot "false";\n').encode()
    security = Path('/etc/apt/apt.conf.d/52pi-server-security')
    if security.exists() and security.read_bytes() != planned[str(security)]:
        raise RuntimeError('Existing managed security update settings differ; review before replacing.')
    for target, content in planned.items():
        atomic_write(target, content, backups)
    scan = subprocess.run(['smartctl', '--scan-open'], capture_output=True, text=True)
    (BASE / 'logs').mkdir(exist_ok=True)
    (BASE / 'logs/smart-scan.txt').write_text(scan.stdout + scan.stderr)
    if any(line.startswith('/dev/') for line in scan.stdout.splitlines()):
        subprocess.run(['systemctl', 'enable', '--now', 'smartmontools.service'], check=True)
        print('SMART service enabled; inspect each USB bridge result separately from disk health.')
    else:
        print('WARNING: SMART passthrough unavailable; this alone does not mean the HDD failed.')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    # Release 1-6 scheduled a fixed-layout pi-backup.timer. The service is
    # now portable-safe for manual compatibility use, but keeping its old
    # schedule enabled would create a duplicate daily backup beside the new
    # explicit portable-backup timer.
    subprocess.run(['systemctl', 'disable', '--now', 'pi-backup.timer'], check=False)
    subprocess.run(['systemctl', 'enable', 'pi-storage-start.service', 'pi-storage-watch.timer',
                    'pi-storage-metrics.timer'], check=True)
    print('PASS: atomic HDD fstab handling and selective storage startup configured; OS/media fstab entries preserved.')


if __name__ == '__main__':
    main()
