import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'outputs/Rassberi-PI5-Codes' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('manage_selection_tests', SCRIPTS / 'manage.py')
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class ManageSelectionTests(unittest.TestCase):
    manifest = [
        {'name': 'core', 'order': 1},
        {'name': 'on-demand', 'order': 2},
        {'name': 'unselected-hdd-app', 'order': 3},
    ]

    def test_install_touches_all_and_only_saved_install_selection(self):
        selected = manage.selected_apps(self.manifest, {'core', 'on-demand'}, {'core'}, 'install')
        self.assertEqual([app['name'] for app in selected], ['core', 'on-demand'])

    def test_verify_uses_saved_startup_selection(self):
        selected = manage.selected_apps(self.manifest, {'core', 'on-demand'}, {'core'}, 'verify')
        self.assertEqual([app['name'] for app in selected], ['core'])

    def test_explicit_all_is_not_needed_to_install_unselected_app(self):
        selected = manage.selected_apps(self.manifest, {'core'}, {'core'}, 'install', all_apps=True)
        self.assertEqual([app['name'] for app in selected], ['core'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
