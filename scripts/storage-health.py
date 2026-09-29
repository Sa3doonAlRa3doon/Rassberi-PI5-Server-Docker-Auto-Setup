#!/usr/bin/env python3
"""Read SMART from the physical parent of each identity-verified mounted disk."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

from storage_guard import inspect_storage, device_map

CONFIG = Path('/srv/docker/configs/storage.json')
BIT_MESSAGES = {
    0: 'smartctl command could not be parsed',
    1: 'device open/identification failed or device unavailable',
    2: 'SMART command failed or SMART data checksum error',
    3: 'SMART overall status reports DISK FAILING',
    4: 'a current pre-failure attribute is at/below its threshold',
    5: 'an attribute crossed its threshold in the past',
    6: 'device error log contains errors',
    7: 'self-test log contains errors',
}


def command_json(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Block-device lookup failed.')
    return json.loads(result.stdout)


def resolve_physical_disk(source):
    """Follow the mounted partition's unique parent; never guess a USB name."""
    current = os.path.realpath(source)
    seen = set()
    for _ in range(8):
        if current in seen or not current.startswith('/dev/'):
            raise RuntimeError('Block-device ancestry is invalid or cyclic.')
        seen.add(current)
        if not stat.S_ISBLK(os.stat(current).st_mode):
            raise RuntimeError('Verified source is not a block device: ' + current)
        data = command_json(['lsblk', '--json', '--paths', '--nodeps',
                             '--output', 'NAME,TYPE,PKNAME,MODEL', current])
        rows = data.get('blockdevices', [])
        if len(rows) != 1:
            raise RuntimeError('Expected one unambiguous block device.')
        row = rows[0]
        if row.get('type') == 'disk':
            return row['name'], (row.get('model') or '').strip()
        parent = row.get('pkname')
        if row.get('type') != 'part' or not parent:
            raise RuntimeError('Unsupported or ambiguous disk ancestry; no SMART command was sent.')
        current = os.path.realpath(parent if parent.startswith('/dev/') else '/dev/' + parent)
    raise RuntimeError('Block-device ancestry exceeded the safety limit.')


def smart_attempt(device, sat=False):
    args = ['smartctl', '--json=c', '-a']
    if sat:
        args += ['-d', 'sat']
    args.append(device)
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        return {'mode': 'sat' if sat else 'auto', 'exit_status': None,
                'data': {}, 'messages': ['SMART query timed out after 45 seconds.']}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        data = {}
    messages = [x.get('string', '') for x in data.get('smartctl', {}).get('messages', [])]
    if result.stderr.strip():
        messages.append(result.stderr.strip())
    if not data and result.stdout.strip():
        messages.append(result.stdout.strip()[:2000])
    return {'mode': 'sat' if sat else 'auto', 'exit_status': result.returncode,
            'data': data, 'messages': messages}


def has_smart_data(data):
    return any(k in data for k in ('smart_status', 'ata_smart_attributes',
                                  'nvme_smart_health_information_log'))


def interpret(attempt):
    """A nonzero bitmask is not automatically unsupported USB passthrough."""
    data, code = attempt['data'], attempt['exit_status']
    bits = code if isinstance(code, int) and code >= 0 else 0
    reasons = [message for bit, message in BIT_MESSAGES.items() if bits & (1 << bit)]
    reasons.extend(attempt['messages'])
    attrs = {a['id']: a for a in data.get('ata_smart_attributes', {}).get('table', [])}
    def raw(identifier):
        return attrs.get(identifier, {}).get('raw', {}).get('value')
    nvme = data.get('nvme_smart_health_information_log', {})
    metrics = {
        'temperature_c': data.get('temperature', {}).get('current', nvme.get('temperature')),
        'power_on_hours': data.get('power_on_time', {}).get('hours', nvme.get('power_on_hours', raw(9))),
        'reallocated_sectors': raw(5), 'current_pending_sectors': raw(197),
        'offline_uncorrectable_sectors': raw(198), 'udma_crc_errors': raw(199),
        'nvme_percentage_used': nvme.get('percentage_used'),
        'nvme_available_spare_pct': nvme.get('available_spare'),
        'nvme_media_errors': nvme.get('media_errors'),
    }
    passed = data.get('smart_status', {}).get('passed')
    failing = bool(bits & 24) or passed is False or bool(nvme.get('critical_warning', 0))
    pending = (raw(197) or 0) > 0 or (raw(198) or 0) > 0
    concerning = bool(bits & 224) or (raw(5) or 0) > 0 or (raw(199) or 0) > 0 or (nvme.get('media_errors') or 0) > 0
    text = ' '.join(reasons).lower()
    unsupported = data.get('smart_support', {}).get('available') is False or any(
        marker in text for marker in ('unknown usb bridge', 'unsupported usb',
                                      'smart support is: unavailable', 'not supported'))
    if failing or pending:
        status = 'CRITICAL'
        if pending:
            reasons.append('Pending or offline-uncorrectable sectors are nonzero; back up and inspect the disk.')
    elif concerning:
        status = 'WARNING'
    elif not has_smart_data(data):
        status = 'UNSUPPORTED' if unsupported else 'UNAVAILABLE'
        reasons.append('No usable SMART health data; this is not a passing disk-health result.')
    elif bits & 7 or code is None:
        status = 'WARNING'
    else:
        status = 'OK'
    return {'status': status, 'smart_passed': passed, 'exit_status': code,
            'exit_bits': [bit for bit in BIT_MESSAGES if bits & (1 << bit)],
            'model': data.get('model_name') or data.get('model_number') or data.get('product'),
            'metrics': metrics, 'messages': reasons}


def read_health(row, expected):
    result = {'key': row['key'], 'path': row.get('path'), 'source': row.get('source')}
    if not row.get('identity_valid'):
        return {**result, 'status': 'ERROR', 'messages': row.get('errors') or ['Storage identity is not verified; SMART was skipped.']}
    if row['key'] == 'media':
        return {**result, 'status': 'UNSUPPORTED', 'messages': ['microSD has no standardized SMART support. Check filesystem/kernel errors and maintain backups.']}
    if not shutil.which('smartctl'):
        return {**result, 'status': 'UNAVAILABLE', 'messages': ['smartctl is missing; install the smartmontools package.']}
    disk, lsblk_model = resolve_physical_disk(row['source'])
    # Revalidate UUID/source immediately before accessing its physical parent.
    again = inspect_storage(required=[row['key']], write_test=False, require_dirs=False)
    current = next((r for r in again if r['key'] == row['key']), None)
    if not current or not current.get('identity_valid') or os.path.realpath(current['source']) != os.path.realpath(row['source']):
        raise RuntimeError('Mounted source changed during inspection; SMART was skipped.')
    attempts = [smart_attempt(disk)]
    first = attempts[0]
    if row['key'] == 'hdd' and (not has_smart_data(first['data']) or (first.get('exit_status') or 0) & 7):
        attempts.append(smart_attempt(disk, sat=True))
    interpreted = [interpret(a) for a in attempts]
    usable = [i for i, a in enumerate(attempts) if has_smart_data(a['data'])]
    chosen = interpreted[usable[-1]] if usable else interpreted[-1]
    # Never erase a failing health result just because a fallback returned less data.
    severity = {'OK': 0, 'UNSUPPORTED': 1, 'UNAVAILABLE': 1, 'WARNING': 2, 'CRITICAL': 3}
    worst = max(interpreted, key=lambda r: severity[r['status']])
    if severity[worst['status']] >= 2 and severity[worst['status']] > severity[chosen['status']]:
        chosen = {**chosen, 'status': worst['status'], 'messages': chosen['messages'] + worst['messages']}
    model = chosen.get('model') or lsblk_model
    desired = expected.get('model')
    if desired:
        normalized = lambda v: re.sub(r'[^A-Z0-9]', '', v.upper())
        if chosen.get('model') and normalized(desired) not in normalized(chosen['model']):
            chosen['status'] = 'CRITICAL'
            chosen['messages'].append('SMART model differs from configured HDD model: ' + desired)
        elif not model or normalized(desired) not in normalized(model):
            chosen['messages'].append('The USB bridge did not expose a matching model; UUID/mount verification still passed.')
    return {**result, **chosen, 'physical_device': disk, 'model': model,
            'attempts': [{'mode': a['mode'], 'exit_status': a['exit_status'], 'messages': a['messages']} for a in attempts]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo to read block-device health.')
    config = device_map(CONFIG)
    rows = inspect_storage(write_test=False, require_dirs=False)
    results = []
    for row in rows:
        try:
            results.append(read_health(row, config[row['key']]))
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            results.append({'key': row['key'], 'status': 'ERROR', 'messages': [str(exc)]})
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            print(f'{result["status"]}: {result["key"]} {result.get("physical_device", "")}; model {result.get("model") or "not available"}')
            if 'smart_passed' in result:
                print('  SMART overall: ' + ('PASSED' if result['smart_passed'] is True else 'FAILED' if result['smart_passed'] is False else 'not available'))
                print(f'  smartctl exit status: {result["exit_status"]}; active bits: {result["exit_bits"]}')
            for name, value in result.get('metrics', {}).items():
                print(f'  {name}: {value if value is not None else "not available"}')
            for message in result.get('messages', []):
                print('  ' + message)
        print('SMART cannot guarantee future reliability. USB passthrough unsupported is a visibility warning, not proof of disk failure.')
    return 2 if any(r['status'] in {'CRITICAL', 'ERROR'} for r in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
