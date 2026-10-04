#!/usr/bin/env python3
"""Interactive terminal selector for installed and boot-start applications."""
import argparse
import json
from pathlib import Path
import os
import sys

import app_selection

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


def main(base):
    if getattr(os, 'geteuid', lambda: 0)() != 0:
        raise SystemExit('Run with sudo.')
    manifest_path = base / 'manifest.json'
    if not manifest_path.is_file():
        raise SystemExit('No server package found at ' + str(base))
    manifest = json.loads(manifest_path.read_text())
    names = [app['name'] for app in sorted(manifest, key=lambda item: item.get('order', 50))
             if not app.get('blocked_reason')]
    installed = app_selection.installed_names(base, manifest)
    startup = app_selection.startup_names(base, manifest)
    selected = ask('Applications to install and keep available:', names, installed)
    selected = app_selection.ordered_names(selected, manifest)
    boot = ask('Applications to start automatically at boot:', selected, [name for name in startup if name in selected])
    result = app_selection.save_selection(base, manifest, selected, boot)
    print(json.dumps(result, indent=2))
    print('Next: review Storage & placement in the settings page, then run install-all.sh')


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--base', default='/srv/docker', help='downloaded or installed package directory')
        args = parser.parse_args()
        main(Path(args.base).resolve())
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
