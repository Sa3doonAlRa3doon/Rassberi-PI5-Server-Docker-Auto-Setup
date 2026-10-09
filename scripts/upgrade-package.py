#!/usr/bin/env python3
"""Stage a reviewed package expansion without replacing private/runtime state."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
TARGET = Path('/srv/docker')
RELEASE_FILE = 'RELEASE.json'
RELEASE_CODE = 'FIXED AND IMPROVED'
PROTECTED = {
    'configs/storage.json', 'configs/layout.json', 'configs/portable-backup.json',
    'configs/storage-autostart.json', 'configs/storage-review-required.json',
    'configs/storage-paused.json', 'configs/storage-start-pending.json',
    'configs/storage-preferences.json', 'enabled-apps.txt', 'installed-apps.txt', 'server.env',
    'app passwords.txt',
    'configs/app-selection.json',
}
RUNTIME_PARTS = {'appdata', 'databases', 'backups', 'logs', '__pycache__', '.git'}
# Explicitly withdrawn projects are stopped and moved into the upgrade backup
# so an older installation cannot keep an unmanaged container running. Their
# application data is never deleted.
RETIRED_APPS = {'chronosnap'}


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        while block := handle.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def sha256_bytes(content):
    return hashlib.sha256(content).hexdigest()


def atomic(path, content, mode):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path.absolute():
        raise RuntimeError('Symlinked managed target: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_release(path):
    path = Path(path)
    if not path.is_file():
        return None
    release = json.loads(path.read_text())
    if (not isinstance(release, dict) or release.get('release_code') != RELEASE_CODE or
            release.get('state') != 'published' or
            not isinstance(release.get('release_id'), int) or release['release_id'] < 1):
        raise RuntimeError('Invalid release marker; expected a published FIXED AND IMPROVED package')
    return release


def release_gate():
    """Allow only a published package newer than the installed release."""
    incoming = read_release(SOURCE / RELEASE_FILE)
    if incoming is None:
        raise RuntimeError('Package has no RELEASE.json; code updates require a published release')
    installed = read_release(TARGET / RELEASE_FILE)
    if installed and incoming['release_id'] <= installed['release_id']:
        raise RuntimeError(
            f"No newer published release: installed {installed['release_id']}, "
            f"package {incoming['release_id']}. Increment release_id only when the package is fixed and ready."
        )
    return incoming, installed


def deployed_replacements():
    path = TARGET / 'configs/layout.json'
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    placements = data.get('placements', {})
    if not isinstance(placements, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in placements.items()):
        raise RuntimeError('Invalid deployed storage layout; review before upgrade')
    return placements


def staged_storage_helpers(stage):
    """Load the staged layout helpers without importing an installed release."""
    guard = load_module('release_storage_guard', stage / 'scripts/storage_guard.py')
    restart = load_module('release_docker_restart', stage / 'scripts/docker_restart.py')
    # storage_setup imports these helpers by their normal module names. Bind
    # staged copies just while it is imported so a downloaded release is
    # rendered by its own reviewed helper, not by an older installed copy.
    previous_guard = sys.modules.get('storage_guard')
    previous_restart = sys.modules.get('docker_restart')
    sys.modules['storage_guard'] = guard
    sys.modules['docker_restart'] = restart
    try:
        setup = load_module('release_storage_setup', stage / 'scripts/storage_setup.py')
    finally:
        if previous_guard is None:
            sys.modules.pop('storage_guard', None)
        else:
            sys.modules['storage_guard'] = previous_guard
        if previous_restart is None:
            sys.modules.pop('docker_restart', None)
        else:
            sys.modules['docker_restart'] = previous_restart
    return setup, guard


def prepared_source():
    temporary = tempfile.TemporaryDirectory(prefix='pi-release-')
    stage = Path(temporary.name) / 'package'
    shutil.copytree(SOURCE, stage, ignore=shutil.ignore_patterns('logs', '__pycache__', '.git'))
    replacements = deployed_replacements()
    if replacements:
        setup, guard = staged_storage_helpers(stage)
        manifest = json.loads((stage / 'manifest.json').read_text())
        selection = load_module('release_app_selection', stage / 'scripts/app_selection.py')
        # Layout v2 is intentionally allowed to describe only the apps that
        # are installed.  Keep an inactive app's shipped paths intact so an
        # upgrade never requires its old example HDD/media mount.
        selected_names = set(selection.installed_names(TARGET, manifest))
        files = setup.render_files(stage, replacements, selected_apps=selected_names)
        for path, content in files.items():
            path.write_bytes(content)
        config_path = TARGET / 'configs/storage.json'
        config = json.loads(config_path.read_text())
        for app in manifest:
            if app['name'] not in selected_names:
                continue
            for item in app.get('directories', []):
                item['path'] = setup.mapped_path(item['path'], replacements)
            database = app.get('database') or {}
            if database.get('path'):
                database['path'] = setup.mapped_path(database['path'], replacements)
        for app in manifest:
            if app['name'] not in selected_names:
                continue
            app['mounts'] = [key for key in guard.app_requirements(app, config) if key != 'root']
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return temporary, stage


def files(stage):
    for path in stage.rglob('*'):
        if not path.is_file() or path.name == 'release-index.json':
            continue
        rel = path.relative_to(stage).as_posix()
        if set(path.relative_to(stage).parts) & RUNTIME_PARTS or rel in PROTECTED or path.name == '.env':
            continue
        yield rel, path


def custom_layout_context(stage):
    """Return safe reverse rendering state for a deployed custom layout.

    Custom layout application files are generated from reviewed canonical
    package files, so their literal hashes differ from release-index hashes.
    Reversing *only* the declared storage substitutions lets the updater
    recognize that generated state while still preserving any unrelated local
    edit.  Releases before the layout fingerprint existed use this path too.
    """
    replacements = deployed_replacements()
    manifest_path = TARGET / 'manifest.json'
    config_path = TARGET / 'configs/storage.json'
    if not replacements or not manifest_path.is_file() or not config_path.is_file():
        return None
    setup, guard = staged_storage_helpers(stage)
    target_manifest = json.loads(manifest_path.read_text())
    selection = load_module('release_app_selection_for_plan', stage / 'scripts/app_selection.py')
    selected = set(selection.installed_names(TARGET, target_manifest))
    return {
        'setup': setup,
        'guard': guard,
        'replacements': replacements,
        'inverse': {target: source for source, target in replacements.items()},
        'selected': selected,
        'target_storage': json.loads(config_path.read_text()),
        'canonical_manifest': json.loads((SOURCE / 'manifest.json').read_text()),
    }


def normalize_manifest_for_layout(content, context):
    """Undo only generated paths and generated mount keys in manifest bytes."""
    try:
        manifest = json.loads(content)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(manifest, list):
        return None
    canonical = {app.get('name'): app for app in context['canonical_manifest'] if isinstance(app, dict)}
    setup, guard = context['setup'], context['guard']
    for app in manifest:
        if not isinstance(app, dict) or app.get('name') not in context['selected']:
            continue
        # Calculate the expected generated mount keys while paths still refer
        # to the deployed storage profile.  After reverse rendering those
        # paths, the custom profile would no longer recognize them and a
        # genuine generated manifest could be mistaken for a manual edit.
        try:
            expected = [key for key in guard.app_requirements(copy.deepcopy(app), context['target_storage'])
                        if key != 'root']
        except RuntimeError:
            return None
        for directory in app.get('directories', []):
            if isinstance(directory, dict) and isinstance(directory.get('path'), str):
                directory['path'] = setup.mapped_path(directory['path'], context['inverse'])
        database = app.get('database') or {}
        if isinstance(database, dict) and isinstance(database.get('path'), str):
            database['path'] = setup.mapped_path(database['path'], context['inverse'])
        # Mount keys are derived from the saved storage profile. Replace them
        # only when they exactly match that derived result; a hand-edited mount
        # list therefore remains different and is preserved for manual review.
        if app.get('mounts', []) == expected and app.get('name') in canonical:
            app['mounts'] = canonical[app['name']].get('mounts', [])
    return (json.dumps(manifest, indent=2) + '\n').encode()


def normalize_compose_for_layout(content, context):
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    for service in value.get('services', {}).values():
        if not isinstance(service, dict):
            return None
        for volume in service.get('volumes', []):
            if isinstance(volume, dict) and isinstance(volume.get('source'), str):
                volume['source'] = context['setup'].mapped_path(volume['source'], context['inverse'])
    return (json.dumps(value, indent=2) + '\n').encode()


def normalize_env_for_layout(content, context):
    try:
        text = content.decode()
    except UnicodeDecodeError:
        return None
    lines = []
    for line in text.splitlines(keepends=True):
        entry = re.fullmatch(r'([A-Z][A-Z0-9_]*(?:_PATH|_DIR|_ROOT))=(.*?)(\r?\n|$)', line)
        if entry and not re.search(r'PASS|TOKEN|SECRET|KEY|CREDENTIAL', entry[1]):
            value = entry[2]
            quote = value[0] if len(value) > 1 and value[0] in "\"'" and value[-1] == value[0] else ''
            raw = value[1:-1] if quote else value
            line = entry[1] + '=' + quote + context['setup'].mapped_path(raw, context['inverse']) + quote + entry[3]
        lines.append(line)
    return ''.join(lines).encode()


def normalized_layout_hash(rel, destination, context):
    """Return the canonical hash for a generated custom-layout file, if any."""
    if context is None or not Path(destination).is_file():
        return None
    content = Path(destination).read_bytes()
    if rel == 'manifest.json':
        normalized = normalize_manifest_for_layout(content, context)
    elif rel.startswith('compose/'):
        parts = Path(rel).parts
        if len(parts) < 3 or parts[1] not in context['selected']:
            return None
        if Path(rel).name in {'compose.yml', 'compose.yaml'}:
            normalized = normalize_compose_for_layout(content, context)
        elif Path(rel).name in {'.env.example'}:
            normalized = normalize_env_for_layout(content, context)
        elif Path(rel).suffix == '.py':
            try:
                normalized = context['setup'].python_paths(content.decode(), context['inverse']).encode()
            except (SyntaxError, UnicodeDecodeError):
                normalized = None
        else:
            normalized = None
    else:
        normalized = None
    return sha256_bytes(normalized) if normalized is not None else None


def plan(stage, index):
    changes, preserved = [], []
    layout = custom_layout_context(stage)
    for rel, source in files(stage):
        destination = TARGET / Path(rel)
        current = sha256(destination) if destination.is_file() else None
        after = sha256(source)
        if rel == RELEASE_FILE and current is not None:
            installed = read_release(destination)
            incoming = read_release(source)
            if installed and incoming['release_id'] > installed['release_id']:
                changes.append({'path': rel, 'action': 'replace', 'before': current, 'after': after})
            else:
                preserved.append({'path': rel, 'reason': 'release marker is not newer',
                                  'current': current, 'incoming': after})
            continue
        entry = index.get(rel) or {}
        accepted = set(entry.get('accepted_sha256') or [])
        previous = entry.get('previous_sha256')
        if previous:
            accepted.add(previous)
        if current == after:
            continue
        rendered_current = normalized_layout_hash(rel, destination, layout) if current is not None else None
        if current is None or current in accepted or rendered_current in accepted:
            changes.append({'path': rel, 'action': 'add' if current is None else 'replace',
                            'before': current, 'after': after})
        else:
            preserved.append({'path': rel, 'reason': 'locally changed or from an unknown release',
                              'current': current, 'incoming': after})
    return changes, preserved


def host_units(stage, index):
    result = []
    names = [path.name for path in (stage / 'systemd').iterdir() if path.is_file()]
    for name in names:
        destination = Path('/etc/systemd/system') / name
        source = stage / 'systemd' / name
        rel = 'systemd/' + name
        current = sha256(destination) if destination.is_file() else None
        after = sha256(source)
        entry = index.get(rel) or {}
        accepted = set(entry.get('accepted_sha256') or [])
        previous = entry.get('previous_sha256')
        if previous:
            accepted.add(previous)
        if current == after:
            continue
        if current is None or current in accepted:
            result.append((destination, source, current))
        else:
            raise RuntimeError('Customized systemd unit needs review before upgrade: ' + str(destination))
    return result


def validate_host():
    """Reject an unsupported host before a release can stage package files."""
    subprocess.run([sys.executable, str(SOURCE / 'scripts/platform_check.py')], check=True)
    result = subprocess.run(['systemctl', 'show', 'docker.service', '--property=LoadState', '--value'],
                            capture_output=True, text=True, check=True)
    if result.stdout.strip() != 'loaded':
        raise RuntimeError('A systemd-managed docker.service is required for package upgrades.')


def retired_app_plan():
    """Return withdrawn projects still present in the installed state."""
    target_manifest = json.loads((TARGET / 'manifest.json').read_text())
    installed_names = {app.get('name') for app in target_manifest if isinstance(app, dict)}
    state_path = TARGET / 'configs' / 'app-selection.json'
    state_names = set()
    if state_path.is_file():
        value = json.loads(state_path.read_text())
        state_names = set(value.get('installed', [])) | set(value.get('startup', []))
    for filename in ('installed-apps.txt', 'enabled-apps.txt'):
        path = TARGET / filename
        if path.is_file():
            state_names.update(line.strip() for line in path.read_text().splitlines() if line.strip())
    return sorted(name for name in RETIRED_APPS if name in installed_names or name in state_names or
                  (TARGET / 'compose' / name).exists())


def backup_and_stop_retired(name, destination):
    """Stop and quarantine an explicitly withdrawn app without deleting data."""
    compose_dir = TARGET / 'compose' / name
    if not compose_dir.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copytree(compose_dir, destination, dirs_exist_ok=True)
    compose_file = compose_dir / 'compose.yml'
    env_file = compose_dir / '.env'
    if compose_file.is_file():
        command = ['docker', 'compose', '--project-name', 'pi-' + name,
                   '--project-directory', str(compose_dir)]
        if env_file.is_file():
            command += ['--env-file', str(env_file)]
        command += ['-f', str(compose_file), 'down', '--remove-orphans']
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Could not stop withdrawn ' + name + ': ' + (result.stderr or result.stdout).strip())
    shutil.rmtree(compose_dir)
    return True


def remove_retired_from_selection(name, backup_root):
    """Remove only the withdrawn name from selection state; preserve all data."""
    state_path = TARGET / 'configs' / 'app-selection.json'
    if state_path.is_file():
        original = state_path.read_bytes()
        backup = backup_root / 'state' / 'app-selection.json'
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup.write_bytes(original)
        value = json.loads(original)
        value['installed'] = [item for item in value.get('installed', []) if item != name]
        value['startup'] = [item for item in value.get('startup', []) if item != name]
        atomic(state_path, (json.dumps(value, indent=2) + '\n').encode(), 0o600)
    for filename, mode in [('installed-apps.txt', 0o640), ('enabled-apps.txt', 0o640)]:
        path = TARGET / filename
        if not path.is_file():
            continue
        backup = backup_root / 'state' / filename
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(path, backup)
        lines = [line for line in path.read_text().splitlines() if line.strip() != name]
        atomic(path, ('\n'.join(lines) + ('\n' if lines else '')).encode(), mode)


def retire_apps(names, backup):
    retired = []
    for name in names:
        root = backup / 'retired-apps' / name
        moved = backup_and_stop_retired(name, root / 'compose')
        remove_retired_from_selection(name, root)
        retired.append({'name': name, 'compose_quarantined': moved,
                        'data_preserved': True,
                        'note': 'Application data and bulk files were not deleted.'})
    return retired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply the exact dry-run plan')
    parser.add_argument('--dry-run', action='store_true', help='Explicit read-only mode (the default)')
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise RuntimeError('Choose --dry-run or --apply')
    if os.geteuid() != 0 or os.name != 'posix':
        raise RuntimeError('Run with sudo on a supported Linux ARM64 host')
    validate_host()
    if SOURCE == TARGET or not (TARGET / 'manifest.json').is_file():
        raise RuntimeError('Run this from the new downloaded package against an existing /srv/docker installation')
    if SOURCE.is_symlink() or TARGET.is_symlink():
        raise RuntimeError('Source and installed package must not be symlinks')
    incoming_release, installed_release = release_gate()
    subprocess.run(['python3', str(TARGET / 'scripts/storage_guard.py'), '--only', 'root'], check=True)
    index = json.loads((SOURCE / 'release-index.json').read_text())['files']
    retired = retired_app_plan()
    temporary, stage = prepared_source()
    try:
        changes, preserved = plan(stage, index)
        units = host_units(stage, index)
        report = {'mode': 'apply' if args.apply else 'dry-run', 'changes': changes,
                  'preserved_local_files': preserved,
                  'systemd_changes': [str(row[0]) for row in units],
                  'release_id': incoming_release['release_id'],
                  'release_code': incoming_release['release_code'],
                  'previous_release_id': installed_release['release_id'] if installed_release else None,
                  'retired_apps': retired,
                  'private_state_preserved': sorted(PROTECTED),
                  'next': 'After apply: sudo /srv/docker/install-all.sh'}
        print(json.dumps(report, indent=2))
        if not args.apply:
            return 0
        import fcntl
        lock = open('/run/lock/pi-server.lock', 'a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Recompute under the lock so dry-run information cannot become a stale apply.
        fresh, fresh_preserved = plan(stage, index)
        if fresh != changes or fresh_preserved != preserved:
            raise RuntimeError('Installed files changed after planning; rerun dry-run')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = TARGET / 'backups' / ('package-upgrade-' + stamp)
        backup.mkdir(parents=True, mode=0o700)
        report['retired_apps'] = retire_apps(retired, backup)
        changed = {item['path'] for item in changes}
        for rel in changed:
            destination = TARGET / Path(rel)
            if destination.exists():
                saved = backup / Path(rel)
                saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(destination, saved)
        for destination, _, current in units:
            if current:
                saved = backup / 'host-units' / destination.name
                saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(destination, saved)
        for rel, source in files(stage):
            if rel not in changed:
                continue
            mode = 0o755 if source.suffix in {'.py', '.sh'} or source.name.endswith('.sh') else 0o644
            atomic(TARGET / Path(rel), source.read_bytes(), mode)
        for destination, source, _ in units:
            atomic(destination, source.read_bytes(), 0o644)
        atomic(backup / 'report.json', (json.dumps(report, indent=2) + '\n').encode(), 0o600)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', 'pi-storage-start.service',
                        'pi-storage-watch.timer', 'pi-storage-resume.timer',
                        'pi-storage-metrics.timer'], check=True)
        print('STAGED: package files upgraded; secrets, enabled-apps, storage identity and data were preserved.')
        print('NEXT: sudo /srv/docker/install-all.sh')
        return 0
    finally:
        temporary.cleanup()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError, BlockingIOError) as exc:
        print('ERROR: ' + str(exc), file=__import__('sys').stderr)
        raise SystemExit(1)
