import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'outputs/Rassberi-PI5-Codes/scripts'
sys.path.insert(0, str(SCRIPTS))
import app_selection
import storage_guard as guard


class CustomSelectionGuardTests(unittest.TestCase):
    def test_root_check_ignores_deselected_hdd_application(self):
        manifest = [
            {'name': 'core', 'order': 1, 'directories': [{'path': '/srv/docker/appdata/core'}]},
            {'name': 'hdd-app', 'order': 2, 'directories': [{'path': '/mnt/hdd/hdd-app'}]},
        ]
        config = {'version': 2, 'devices': {
            'root': {'mount': '/', 'uuid': 'root-uuid', 'filesystem': 'ext4'},
        }}
        root = {'target': '/', 'source': '/dev/nvme0n1p2', 'fstype': 'ext4',
                'uuid': 'root-uuid', 'options': 'rw,relatime'}
        free = types.SimpleNamespace(f_bavail=100 * 1024**3, f_bfree=100 * 1024**3,
                                     f_frsize=1, f_blocks=200 * 1024**3)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'manifest.json').write_text(json.dumps(manifest))
            app_selection.save_selection(base, manifest, ['core'], ['core'])
            self.assertEqual([app['name'] for app in guard.selected_manifest(base / 'manifest.json')], ['core'])
            with patch.object(guard, 'mounted', return_value=root), \
                 patch.object(guard, 'containing_mount', return_value=root), \
                 patch.object(guard.os.path, 'realpath', side_effect=lambda path: str(path)), \
                 patch.object(guard.os.path, 'exists', return_value=True), \
                 patch.object(guard.os, 'statvfs', return_value=free, create=True):
                rows = guard.inspect_storage(required=['root'], manifest=base / 'manifest.json', config=config)
        self.assertFalse(rows[0]['errors'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
