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
spec = importlib.util.spec_from_file_location('settings_selection_tests', SCRIPTS / 'settings_server.py')
settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(settings)


class SettingsSelectionTests(unittest.TestCase):
    def test_empty_saved_startup_selection_stays_empty(self):
        manifest = [
            {'name': 'core', 'order': 1, 'default_enabled': True},
            {'name': 'on-demand', 'order': 2, 'default_enabled': False},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'manifest.json').write_text(json.dumps(manifest))
            (base / 'installed-apps.txt').write_text('core\n')
            (base / 'enabled-apps.txt').write_text('')
            with patch.object(settings, 'BASE', base):
                self.assertEqual(settings.selected_apps(), [])
            (base / 'enabled-apps.txt').unlink()
            with patch.object(settings, 'BASE', base):
                self.assertEqual(settings.selected_apps(), ['core'])

    def test_atomic_selection_state_is_authoritative_when_compatibility_file_is_missing(self):
        manifest = [{'name': 'core', 'order': 1, 'default_enabled': True}]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'manifest.json').write_text(json.dumps(manifest))
            settings.app_selection.save_selection(base, manifest, ['core'], [])
            (base / 'enabled-apps.txt').unlink()
            with patch.object(settings, 'BASE', base):
                self.assertEqual(settings.selected_apps(), [])

    def test_snapshot_marks_unprepared_selected_apps(self):
        manifest = [{'name': 'core', 'order': 1, 'default_enabled': True}]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'manifest.json').write_text(json.dumps(manifest))
            settings.app_selection.save_selection(base, manifest, ['core'], [])
            with patch.object(settings, 'BASE', base), patch.object(settings, 'DEMO', True):
                state = settings.snapshot()
            self.assertFalse(state['apps'][0]['prepared'])

    def test_failed_removed_app_stop_keeps_old_selection_authoritative(self):
        manifest = [
            {'name': 'core', 'order': 1, 'default_enabled': True},
            {'name': 'removed', 'order': 2, 'default_enabled': True},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'manifest.json').write_text(json.dumps(manifest))
            settings.app_selection.save_selection(base, manifest, ['core', 'removed'], ['core', 'removed'])
            with patch.object(settings, 'BASE', base), \
                 patch.object(settings, 'with_lock', side_effect=lambda callback: callback()), \
                 patch.object(settings, 'deployed', return_value=True), \
                 patch.object(settings, 'external', side_effect=RuntimeError('simulated Docker stop failure')):
                with self.assertRaisesRegex(RuntimeError, 'simulated Docker stop failure'):
                    settings.dispatch('save-apps', {'installed': ['core'], 'enabled': ['core']})
            state = settings.app_selection.selection_state(base)
            self.assertEqual(state['installed'], ['core', 'removed'])
            self.assertEqual(state['startup'], ['core', 'removed'])

    def test_removed_app_stops_before_selection_is_committed(self):
        manifest = [
            {'name': 'core', 'order': 1, 'default_enabled': True},
            {'name': 'removed', 'order': 2, 'default_enabled': True},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'manifest.json').write_text(json.dumps(manifest))
            settings.app_selection.save_selection(base, manifest, ['core', 'removed'], ['core', 'removed'])
            observed = []
            def stop(command):
                observed.append(settings.app_selection.selection_state(base)['installed'])
                return {'completed': True}
            with patch.object(settings, 'BASE', base), \
                 patch.object(settings, 'with_lock', side_effect=lambda callback: callback()), \
                 patch.object(settings, 'deployed', return_value=True), \
                 patch.object(settings, 'external', side_effect=stop):
                result = settings.dispatch('save-apps', {'installed': ['core'], 'enabled': ['core']})
            self.assertEqual(observed, [['core', 'removed']])
            self.assertEqual(result['stopped'], ['removed'])
            self.assertEqual(settings.app_selection.selection_state(base)['installed'], ['core'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
