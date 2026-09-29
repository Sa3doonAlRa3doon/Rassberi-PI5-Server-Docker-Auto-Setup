#!/usr/bin/env python3
"""Resolve only identity-verified configured disks; never guess USB device letters."""
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

BASE = Path('/srv/docker')
sys.path.insert(0, str(BASE / 'scripts'))
import storage_guard as guard


def atomic_json(path, value):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError('Refusing symlink: ' + str(path))
    tmp = path.with_name(path.name + '.monitoring-tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def physical_disk(source):
    current = Path(os.path.realpath(source))
    seen = set()
    for _ in range(8):
        if str(current) in seen or not str(current).startswith('/dev/') or not stat.S_ISBLK(current.stat().st_mode):
            raise RuntimeError('Invalid block-device ancestry')
        seen.add(str(current))
        result = subprocess.check_output(['lsblk','--json','--paths','--nodeps','--output','NAME,TYPE,PKNAME,MODEL',str(current)], text=True)
        rows = json.loads(result)['blockdevices']
        if len(rows) != 1:
            raise RuntimeError('Ambiguous block-device ancestry')
        row = rows[0]
        if row['type'] == 'disk':
            return current, (row.get('model') or '').strip()
        parent = row.get('pkname')
        if row['type'] != 'part' or not parent:
            raise RuntimeError('Unsupported block-device ancestry')
        current = Path(os.path.realpath(parent if parent.startswith('/dev/') else '/dev/' + parent))
    raise RuntimeError('Too many block-device ancestors')


def stable_source(disk):
    candidates = []
    for p in Path('/dev/disk/by-id').glob('*'):
        if '-part' in p.name or not p.is_symlink():
            continue
        if p.resolve() == disk.resolve():
            candidates.append(p)
    if not candidates:
        raise RuntimeError('No stable /dev/disk/by-id identity for ' + str(disk))
    candidates.sort(key=lambda p: (not p.name.startswith(('wwn-', 'nvme-eui.')), str(p)))
    return str(candidates[0])


def discovered():
    config = guard.load_config(BASE / 'configs/storage.json')
    configured = guard.device_map(config) if hasattr(guard, 'device_map') else config.get('devices', config)
    # Validate the state directory separately. Optional missing disks cannot prevent CPU monitoring.
    guard.check(required=['root'], manifest=BASE/'manifest.json', config=config)
    result = []
    seen = set()
    for key, definition in configured.items():
        try:
            rows = guard.check(required=[key], manifest=[], config=config)
            source = guard.mounted(definition['mount'])['source']
            disk, model = physical_disk(source)
            if str(disk).startswith('/dev/mmcblk') or disk in seen:
                continue
            expected_model = (definition.get('model') or '').strip()
            if expected_model and expected_model.lower() not in model.lower():
                raise RuntimeError('Drive model differs from configured identity')
            by_id = stable_source(disk)
            disk_type = 'nvme' if disk.name.startswith('nvme') else 'sat'
            # Match container device name to the verified disk so smartctl scan can recognize it.
            result.append({'key':key,'source':by_id,'target':str(disk),'type':disk_type,'model':model})
            seen.add(disk)
        except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            print('SMART unavailable for ' + str(key) + ': ' + str(exc), flush=True)
    return result


def configure(app):
    if app not in {'beszel','scrutiny'}:
        raise RuntimeError('Unsupported monitoring app')
    rows = discovered()
    path = BASE/'compose'/app/'compose.yml'
    config = json.loads(path.read_text(encoding='utf-8'))
    target = config['services']['beszel-agent' if app == 'beszel' else 'scrutiny']
    target['devices'] = [{'source':r['source'],'target':r['target'],'permissions':'r'} for r in rows]
    if app == 'beszel':
        target['environment']['SMART_DEVICES'] = ','.join(r['target'] + ':' + r['type'] for r in rows)
    else:
        collector = {'version':1,'host':{'id':'raspberry-pi'},
                     'devices':[{'device':r['target'],'type':r['type']} for r in rows],
                     'allow_listed_devices':[r['target'] for r in rows] or ['/dev/NO_VERIFIED_SMART_DEVICE']}
        atomic_json(BASE/'configs/scrutiny/collector.yaml', collector)
    atomic_json(path, config)
    atomic_json(BASE/'configs'/app/'verified-devices.json', rows)
    print(f'{app}: configured {len(rows)} verified SMART disks; microSD is excluded.', flush=True)


if __name__ == '__main__':
    configure(sys.argv[1])
