#!/usr/bin/env python3
"""Interactive terminal selector for installed and boot-start applications."""
import json
from pathlib import Path
import sys

import app_selection

BASE = Path('/srv/docker')


def ask(prompt, names, default):
    print(prompt)
    for index, name in enumerate(names, 1):
        print(f'  {index:2d}. {name}')
    value = input(f'Enter numbers/names, "all", or Enter for [{", ".join(default)}]: ').strip()
    if not value:
        return list(default)
    if value.lower() == 'all':
        return list(names)
    result = []
    for token in value.replace(',', ' ').split():
        if token.isdigit() and 1 <= int(token) <= len(names):
            result.append(names[int(token) - 1])
        elif token in names:
            result.append(token)
        else:
            raise ValueError('Unknown application or number: ' + token)
    return result


def main():
    if __import__('os').geteuid() != 0:
        raise SystemExit('Run with sudo.')
    manifest = json.loads((BASE / 'manifest.json').read_text())
    names = [app['name'] for app in sorted(manifest, key=lambda item: item.get('order', 50))
             if not app.get('blocked_reason')]
    installed = app_selection.installed_names(BASE, manifest)
    startup = app_selection.startup_names(BASE, manifest)
    selected = ask('Applications to install and keep available:', names, installed)
    selected = app_selection.ordered_names(selected, manifest)
    boot = ask('Applications to start automatically at boot:', selected, [name for name in startup if name in selected])
    result = app_selection.save_selection(BASE, manifest, selected, boot)
    print(json.dumps(result, indent=2))
    print('Next: review Storage & placement in the settings page, then run sudo /srv/docker/install-all.sh')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)

