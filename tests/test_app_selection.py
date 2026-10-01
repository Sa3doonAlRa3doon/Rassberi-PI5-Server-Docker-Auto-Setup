import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('app_selection_tests', ROOT / 'outputs/Rassberi-PI5-Codes/scripts/app_selection.py')
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)


class AppSelectionTests(unittest.TestCase):
    def test_requested_services_are_default_startup_apps(self):
        manifest = json.loads((ROOT / 'outputs/Rassberi-PI5-Codes/manifest.json').read_text(encoding='utf-8-sig'))
        defaults = {app['name'] for app in manifest if app.get('default_enabled') is True}
        self.assertTrue({'onlyoffice', 'jupyter', 'stirling-pdf'} <= defaults)

    def manifest(self):
        return [
            {'name': 'base', 'order': 1},
            {'name': 'optional', 'order': 2, 'requires': ['base']},
            {'name': 'blocked', 'order': 3, 'blocked_reason': 'unsupported'},
        ]

    def test_dependencies_are_added_in_manifest_order(self):
        self.assertEqual(selection.ordered_names(['optional'], self.manifest()), ['base', 'optional'])

    def test_unknown_and_empty_selections_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unknown application'):
            selection.ordered_names(['missing'], self.manifest())
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'at least one'):
                selection.save_selection(Path(tmp), self.manifest(), [], [])

    def test_save_selection_separates_installed_and_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = selection.save_selection(Path(tmp), self.manifest(), ['optional'], ['optional'])
            self.assertEqual(result['installed'], ['base', 'optional'])
            self.assertEqual(selection.read_names(Path(tmp) / 'installed-apps.txt'), ['base', 'optional'])
            self.assertEqual(selection.read_names(Path(tmp) / 'enabled-apps.txt'), ['base', 'optional'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
