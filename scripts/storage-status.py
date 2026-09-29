#!/usr/bin/env python3
"""Report verified filesystems; never run df on an unmounted directory."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from storage_guard import inspect_storage

BASE = Path('/srv/docker')
METRICS = BASE / 'appdata/storage-metrics/status.json'
LABELS = {'root': 'NVMe /', 'hdd': 'HDD /mnt/hdd', 'media': 'microSD /mnt/media'}


def human_bytes(value):
    return 'N/A' if value is None else f'{value / (1024 ** 3):.2f} GiB'


def summarize(rows):
    """Invalid identity has no capacity, even if the input includes fallback data."""
    drives = {}
    for row in rows:
        key = row['key']
        valid = row.get('identity_valid') is True
        total = row.get('total_bytes') if valid else None
        used = row.get('used_bytes') if valid else None
        free = row.get('free_bytes') if valid else None
        pct = row.get('used_pct') if valid else None
        drives[key] = {
            'key': key, 'path': row.get('path'), 'identity_valid': valid,
            'status': row.get('status', 'ERROR'),
            'source': row.get('source') if valid else None,
            'uuid': row.get('uuid') if valid else None,
            'filesystem': row.get('filesystem') if valid else None,
            'total_bytes': total, 'used_bytes': used, 'free_bytes': free,
            'used_pct': pct, 'errors': row.get('errors', []),
            'warnings': row.get('warnings', []),
            'display': {'status': row.get('status', 'ERROR'),
                        'total': human_bytes(total), 'used': human_bytes(used),
                        'free': human_bytes(free),
                        'percent': 'N/A' if pct is None else f'{pct:.1f}%'},
        }
    now = datetime.now(timezone.utc)
    return {'generated_at': now.isoformat(), 'generated_unix': now.timestamp(),
            'thresholds': {'INFO': 70, 'WARNING': 80, 'CRITICAL': 90, 'EMERGENCY': 95},
            'drives': drives}


def write_metrics(report, destination=METRICS):
    # Only the already-verified NVMe is allowed to receive status files.
    if not report['drives'].get('root', {}).get('identity_valid'):
        raise RuntimeError('Root filesystem identity is invalid; refusing to write metrics.')
    destination = Path(destination)
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.status-', suffix='.json', dir=destination.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def print_report(report):
    print('Verified storage at ' + report['generated_at'])
    print(f'{"Drive / mount":24} {"Status":10} {"Total":14} {"Used":14} {"Free":14} {"Used %":8}')
    for key, row in report['drives'].items():
        d = row['display']
        label = key + ' ' + row['path']
        print(f'{label:24} {d["status"]:10} {d["total"]:14} {d["used"]:14} {d["free"]:14} {d["percent"]:8}')
        if row['identity_valid']:
            print(f'  Source: {row["source"]}; filesystem: {row["filesystem"]}; UUID: {row["uuid"] or "not configured"}')
        for message in row['errors']:
            print('  ERROR: ' + message)
        for message in row['warnings']:
            print('  WARNING: ' + message)
    print('Capacity levels: 70% INFO; 80% WARNING; 90% CRITICAL; 95% EMERGENCY.')
    print('N/A means that the expected mounted filesystem was not verified; it never means zero usage.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--write-metrics', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--check', action='store_true', help='Return failure for ERROR, CRITICAL, or EMERGENCY')
    args = parser.parse_args()
    report = summarize(inspect_storage(write_test=False, require_dirs=False))
    if args.write_metrics:
        write_metrics(report)
    if not args.quiet:
        print(json.dumps(report, indent=2)) if args.json else print_report(report)
    return 2 if args.check and any(row['status'] in {'ERROR', 'CRITICAL', 'EMERGENCY'}
                                 for row in report['drives'].values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
