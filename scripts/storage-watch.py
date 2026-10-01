#!/usr/bin/env python3
"""Pause only containers that depend on a missing or unsafe data drive."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from docker_restart import restart_policy_option

BASE = Path('/srv/docker')
PAUSED = BASE / 'configs/storage-paused.json'
LOCK = Path('/run/lock/pi-server.lock')


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path, fallback):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, list) else fallback
    except (OSError, ValueError):
        return fallback


def inspect_containers():
    ids = subprocess.run(['docker', 'ps', '-aq'], capture_output=True, text=True, check=True).stdout.split()
    if not ids:
        return []
    return json.loads(run(['docker', 'inspect', *ids], capture_output=True, text=True).stdout)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('storage-watch.py must run as root')
    import fcntl
    lock = open(LOCK, 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return 0
    guard_path = BASE / 'scripts' / 'storage_guard.py'
    import importlib.util
    spec = importlib.util.spec_from_file_location('pi_storage_guard', guard_path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    manifest = guard.selected_manifest(BASE / 'manifest.json', BASE)
    rows = guard.inspect_storage(manifest=[],
                                 config=BASE / 'configs' / 'storage.json')
    bad = {row['key'] for row in rows if row['errors']}
    root_bad = 'root' in bad
    if root_bad:
        subprocess.run(['logger', '-p', 'daemon.crit', 'NVMe root storage is unsafe; stopping Docker'], check=False)
        subprocess.run(['systemctl', 'stop', 'docker.socket', 'docker.service'], check=False)
        lock.close()
        return 1
    apps = {app['name']: app for app in manifest}
    paused = read_json(PAUSED, [])
    paused_ids = {item.get('id') for item in paused}
    containers = inspect_containers()
    unsafe_apps = set()
    for name, app in apps.items():
        app_rows = guard.inspect_storage(required=guard.app_requirements(app), manifest=[app], require_dirs=True)
        if any(row['errors'] for row in app_rows):
            unsafe_apps.add(name)
    containers.sort(key=lambda c: c.get('Config', {}).get('Labels', {}).get('com.docker.compose.service') in {'db', 'redis'})
    for container in containers:
        project = container.get('Config', {}).get('Labels', {}).get('com.docker.compose.project', '')
        app_name = project[3:] if project.startswith('pi-') else ''
        app = apps.get(app_name)
        if not app or app_name not in unsafe_apps:
            continue
        status = container.get('State', {}).get('Status')
        if status not in {'running', 'restarting'}:
            continue
        if container['Id'] not in paused_ids:
            paused.append({'id': container['Id'], 'name': container.get('Name', '').lstrip('/'),
                           'app': app_name, 'service': container.get('Config', {}).get('Labels', {}).get('com.docker.compose.service', ''),
                           'reason': sorted(bad & set(guard.app_requirements(app))),
                           'restart': container['HostConfig']['RestartPolicy']})
            paused_ids.add(container['Id'])
            # Persist intent before the stop, so interruption cannot lose the resume record.
            write_json(PAUSED, paused)
        run(['docker', 'update', '--restart=no', container['Id']], stdout=subprocess.DEVNULL)
        run(['docker', 'stop', '--time', '90', container['Id']], stdout=subprocess.DEVNULL)
        subprocess.run(['logger', '-p', 'daemon.warning',
                        f'Paused {app_name}/{container.get("Name", "")} because storage is unavailable'], check=False)
    holds = set(read_json(BASE / 'configs/storage-review-required.json', []))
    if paused:
        remaining = []
        for app_name in sorted({item.get('app') for item in paused}):
            if app_name in holds or app_name in unsafe_apps:
                remaining.extend(item for item in paused if item.get('app') == app_name)
                continue
            group = [item for item in paused if item.get('app') == app_name]
            app = apps.get(app_name)
            try:
                if not app:
                    raise RuntimeError('Application is no longer in manifest')
                guard.check(required=guard.app_requirements(app), manifest=[app],
                            require_dirs=True, config=BASE / 'configs/storage.json')
                restart_options = {item['id']: restart_policy_option(item.get('restart')) for item in group}
                if len(restart_options) != len(group):
                    raise RuntimeError('Duplicate paused container id')
            except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                remaining.extend(group)
                subprocess.run(['logger', '-p', 'daemon.warning',
                                f'Delayed resume for {app_name}: {exc}'], check=False)
                continue
            group.sort(key=lambda item: item.get('service') not in {'db', 'redis'})
            for index, item in enumerate(group):
                guard.check(required=guard.app_requirements(app), manifest=[app], require_dirs=True,
                            config=BASE / 'configs/storage.json')
                if item['id'] not in {c['Id'] for c in containers}:
                    # It was intentionally removed/recreated; never start a replacement by name.
                    continue
                result = subprocess.run(['docker', 'update', '--restart=' + restart_options[item['id']], item['id']],
                                        capture_output=True, text=True)
                if result.returncode:
                    remaining.append(item)
                    continue
                result = subprocess.run(['docker', 'start', item['id']], capture_output=True, text=True)
                if result.returncode:
                    remaining.append(item)
                    remaining.extend(other for other in group[index + 1:] if other not in remaining)
                    break
                if item.get('service') in {'db', 'redis'}:
                    import time
                    for _ in range(60):
                        state = json.loads(run(['docker', 'inspect', item['id']], capture_output=True, text=True).stdout)[0]['State']
                        if state.get('Health', {}).get('Status') == 'healthy' or (not state.get('Health') and state['Status'] == 'running'):
                            break
                        time.sleep(2)
                    else:
                        remaining.extend(other for other in group[index:] if other not in remaining)
                        break
            failed_ids = {item['id'] for item in remaining}
            resumed = sum(item['id'] not in failed_ids for item in group)
            subprocess.run(['logger', '-p', 'daemon.info', f'Resumed {resumed}/{len(group)} containers for {app_name}'], check=False)
        paused = remaining
    if paused:
        write_json(PAUSED, paused)
    elif PAUSED.exists():
        PAUSED.unlink()
    lock.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('ERROR: storage watch: ' + str(exc), file=__import__('sys').stderr)
        raise SystemExit(1)
