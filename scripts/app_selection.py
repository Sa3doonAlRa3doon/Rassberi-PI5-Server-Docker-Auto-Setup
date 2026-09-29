#!/usr/bin/env python3
"""Persist and validate the user's installed-app and boot-app selections."""
from pathlib import Path
import os
import tempfile


def read_names(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def ordered_names(names, manifest):
    known = {app['name']: app for app in manifest}
    requested = set(names)
    unknown = requested - set(known)
    if unknown:
        raise ValueError('Unknown application selection: ' + ', '.join(sorted(unknown)))
    # Selecting an app also selects every declared dependency.
    changed = True
    while changed:
        changed = False
        for name in tuple(requested):
            for dependency in known[name].get('requires', []):
                if dependency not in known:
                    raise ValueError(f'{name} requires unknown application {dependency}')
                if dependency not in requested:
                    requested.add(dependency)
                    changed = True
    return [app['name'] for app in sorted(manifest, key=lambda item: item.get('order', 50))
            if app['name'] in requested and not app.get('blocked_reason')]


def installed_names(base, manifest):
    saved = read_names(Path(base) / 'installed-apps.txt')
    if not saved:
        # Existing installations predate custom install selection; preserve their
        # behavior until the owner saves a selection in the settings page.
        saved = [app['name'] for app in manifest if not app.get('blocked_reason')]
    return ordered_names(saved, manifest)


def startup_names(base, manifest):
    installed = set(installed_names(base, manifest))
    saved = read_names(Path(base) / 'enabled-apps.txt')
    return [name for name in saved if name in installed]


def atomic_names(path, names, mode=0o640):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write('\n'.join(names) + ('\n' if names else ''))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_selection(base, manifest, installed, startup):
    installed = ordered_names(installed, manifest)
    if not installed:
        raise ValueError('Select at least one application to install')
    startup = ordered_names(startup, manifest)
    if not set(startup).issubset(installed):
        raise ValueError('Every application selected for startup must also be selected for installation')
    base = Path(base)
    atomic_names(base / 'installed-apps.txt', installed)
    atomic_names(base / 'enabled-apps.txt', startup)
    return {'saved': True, 'installed': installed, 'startup': startup,
            'message': 'Application selection saved. Dependencies were included automatically.'}

