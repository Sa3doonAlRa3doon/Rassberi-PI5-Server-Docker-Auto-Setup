"""Exercise the legacy entry points without Docker, mounts, or production data.

The real snapshot/restore implementation is covered by test_tailscale_portable.
This focused test makes sure the retained command names dispatch only to the
layout-aware implementation and reject the old fixed-layout interface before
it can perform any maintenance action.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1] / 'outputs/Rassberi-PI5-Codes'
BASH = shutil.which('bash') or r'C:\Program Files\Git\bin\bash.exe'
COUNT = 0


def run(script, *arguments):
    return subprocess.run([BASH, str(script), *arguments], text=True,
                          capture_output=True, timeout=20)


def command(stdout):
    return json.loads(stdout)


for relative in ('backup.sh', 'scripts/backup.sh', 'scripts/restore.sh'):
    path = ROOT / relative
    subprocess.run([BASH, '-n', str(path)], check=True)
    assert b'\r\n' not in path.read_bytes(), relative
    COUNT += 1

for relative in ('scripts/backup.sh', 'scripts/restore.sh'):
    text = (ROOT / relative).read_text(encoding='utf-8')
    for forbidden in ('/mnt/hdd', '/mnt/media', '/dev/nvme0n1p2',
                      'a8293b36-2c0e-4852-84fd-92ac7503f4db',
                      '17e44bc7-f360-45c4-878b-a7fe7aa45f6e'):
        assert forbidden not in text, (relative, forbidden)
    assert 'portable-backup.py' in text
    COUNT += 1

with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='backup-wrapper-') as raw:
    temporary = Path(raw)
    scripts = temporary / 'scripts'
    scripts.mkdir()
    backup = scripts / 'backup.sh'
    restore = scripts / 'restore.sh'
    backup.write_bytes((ROOT / 'scripts/backup.sh').read_bytes())
    restore.write_bytes((ROOT / 'scripts/restore.sh').read_bytes())
    portable = scripts / 'portable-backup.py'
    portable.write_text(
        '#!/usr/bin/env python3\n'
        'import json, sys\n'
        'print(json.dumps(sys.argv[1:]))\n', encoding='utf-8')

    result = run(backup, '--plan', '--json')
    assert result.returncode == 0, result.stderr
    dispatched = command(result.stdout)
    assert dispatched[:3] == ['plan', '--config', dispatched[2]]
    assert dispatched[2].replace('\\', '/').endswith('/srv/docker/configs/portable-backup.json')
    assert dispatched[3:] == ['--json']
    COUNT += 1

    result = run(backup, '--json')
    assert result.returncode == 0, result.stderr
    dispatched = command(result.stdout)
    assert dispatched[:3] == ['create', '--config', dispatched[2]]
    assert dispatched[2].replace('\\', '/').endswith('/srv/docker/configs/portable-backup.json')
    assert dispatched[3:] == ['--json']
    COUNT += 1

    result = run(backup, '/root/pi-backup.conf')
    assert result.returncode == 2
    assert 'Legacy backup.conf arguments are unsupported' in result.stderr
    COUNT += 1

    result = run(backup, '--config', '/custom/backup.json', '--json')
    assert result.returncode == 0, result.stderr
    dispatched = command(result.stdout)
    assert dispatched[0] == 'create'
    assert dispatched.count('--config') == 2
    assert dispatched[-3] == '--config'
    assert dispatched[-2].replace('\\', '/').endswith('/custom/backup.json')
    assert dispatched[-1] == '--json'
    COUNT += 1

    result = run(restore, 'verify', '--snapshot', '/portable/snapshot', '--json')
    assert result.returncode == 0, result.stderr
    dispatched = command(result.stdout)
    assert dispatched[:2] == ['verify', '--snapshot']
    assert dispatched[2].replace('\\', '/').endswith('/portable/snapshot')
    assert dispatched[3:] == ['--json']
    COUNT += 1

    result = run(restore, '/portable/snapshot')
    assert result.returncode == 0, result.stderr
    dispatched = command(result.stdout)
    assert dispatched[:2] == ['verify', '--snapshot']
    assert dispatched[2].replace('\\', '/').endswith('/portable/snapshot')
    COUNT += 1

    result = run(restore, '/portable/snapshot', '--confirm-restore')
    assert result.returncode == 2
    assert 'Legacy restore flags are unsupported' in result.stderr
    COUNT += 1

    legacy = temporary / 'legacy-tar-backup'
    legacy.mkdir()
    (legacy / 'nvme.tar.gz').write_bytes(b'not opened')
    result = run(restore, str(legacy))
    assert result.returncode == 2
    assert 'Legacy tar archive refused' in result.stderr
    COUNT += 1

docs = (ROOT / 'BACKUPS.md').read_text(encoding='utf-8')
assert 'portable-backup.sh create' in docs
assert 'deliberately refuses those archives' in docs
assert 'BACKUP_ROOT=' not in docs
COUNT += 1

print(f'PASS: {COUNT} wrapper dispatch, fixed-layout rejection, Bash syntax and documentation checks. No production filesystem/container actions were executed.')
