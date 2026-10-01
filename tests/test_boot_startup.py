import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
# boot-storage.py runs on Linux. Provide the small locking surface it imports so
# its pure ordering function can be exercised from this Windows test workspace.
if sys.platform == 'win32':
    sys.modules.setdefault('fcntl', types.SimpleNamespace(LOCK_EX=0, flock=lambda *_: None))
SPEC = importlib.util.spec_from_file_location(
    'boot_storage_tests', ROOT / 'outputs/Rassberi-PI5-Codes/scripts/boot-storage.py')
boot_storage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boot_storage)


class BootStartupOrderTests(unittest.TestCase):
    def test_requested_heavy_apps_start_before_other_selected_apps(self):
        manifest = json.loads(
            (ROOT / 'outputs/Rassberi-PI5-Codes/manifest.json').read_text(encoding='utf-8-sig'))
        selected = {'docker-socket-proxy', 'nextcloud', 'onlyoffice', 'jupyter', 'stirling-pdf'}
        ordered = boot_storage.startup_order(manifest, selected)
        self.assertEqual(ordered[:3], ['onlyoffice', 'jupyter', 'stirling-pdf'])
        self.assertEqual(set(ordered), selected)

    def test_priority_does_not_override_the_saved_startup_selection(self):
        manifest = json.loads(
            (ROOT / 'outputs/Rassberi-PI5-Codes/manifest.json').read_text(encoding='utf-8-sig'))
        selected = {'docker-socket-proxy', 'nextcloud'}
        self.assertEqual(
            boot_storage.startup_order(manifest, selected),
            ['docker-socket-proxy', 'nextcloud'])

    def test_selected_dependency_starts_before_its_prioritized_dependent(self):
        manifest = [
            {'name': 'dependency', 'order': 99},
            {'name': 'priority-app', 'order': 1, 'boot_priority': 1,
             'requires': ['dependency']},
            {'name': 'ordinary-app', 'order': 2},
        ]
        self.assertEqual(
            boot_storage.startup_order(manifest, {'dependency', 'priority-app', 'ordinary-app'}),
            ['dependency', 'priority-app', 'ordinary-app'])

    def test_dependency_cycle_is_reported(self):
        manifest = [
            {'name': 'first', 'order': 1, 'requires': ['second']},
            {'name': 'second', 'order': 2, 'requires': ['first']},
        ]
        with self.assertRaisesRegex(RuntimeError, 'Startup dependency cycle'):
            boot_storage.startup_order(manifest, {'first', 'second'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
