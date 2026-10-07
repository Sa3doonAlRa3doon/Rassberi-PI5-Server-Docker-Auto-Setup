import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'outputs/Rassberi-PI5-Codes/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('app_selection_tests', ROOT / 'outputs/Rassberi-PI5-Codes/scripts/app_selection.py')
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)
selector_spec = importlib.util.spec_from_file_location('select_apps_tests', SCRIPTS / 'select-apps.py')
selector = importlib.util.module_from_spec(selector_spec)
selector_spec.loader.exec_module(selector)


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

    def test_fresh_install_opens_the_selector_before_docker_checks(self):
        installer = (ROOT / 'outputs/Rassberi-PI5-Codes/install-all.sh').read_text(encoding='utf-8')
        self.assertIn('exec "$SOURCE/setup-server.sh"', installer)
        self.assertLess(installer.index('no Docker application selection has been saved'),
                        installer.index('docker info >/dev/null'))
        selector = (ROOT / 'outputs/Rassberi-PI5-Codes/select-apps.sh').read_text(encoding='utf-8')
        self.assertIn('--base "$BASE"', selector)
        self.assertIn("parser.add_argument('--base'", (ROOT / 'outputs/Rassberi-PI5-Codes/scripts/select-apps.py').read_text(encoding='utf-8'))

    def test_setup_panel_explains_storage_first_and_never_pulls_while_browsing(self):
        html = (ROOT / 'outputs/Rassberi-PI5-Codes/configs/settings-ui/index.html').read_text(encoding='utf-8')
        script = (ROOT / 'outputs/Rassberi-PI5-Codes/configs/settings-ui/app.js').read_text(encoding='utf-8')
        self.assertIn('Choose storage roles first', html)
        self.assertIn('Nothing is pulled while you browse', html)
        self.assertIn('save-storage-preferences', script)
        self.assertIn('state.selection_saved', script)
        self.assertIn('state.layout_saved', script)

    def test_terminal_selector_saves_a_downloaded_package_selection(self):
        manifest = [
            {'name': 'core', 'order': 1},
            {'name': 'optional', 'order': 2, 'requires': ['core']},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'manifest.json').write_text(json.dumps(manifest))
            with patch.object(selector.os, 'geteuid', return_value=0, create=True), \
                 patch('builtins.input', side_effect=['2', '2']):
                selector.main(base)
            self.assertEqual(selection.selection_state(base),
                             {'version': 1, 'installed': ['core', 'optional'], 'startup': ['core', 'optional']})


if __name__ == '__main__':
    unittest.main(verbosity=2)
