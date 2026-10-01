import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'outputs/Rassberi-PI5-Codes' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('prepare_selection_tests', SCRIPTS / 'prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class PrepareSelectionTests(unittest.TestCase):
    manifest = [
        {'name': 'core', 'order': 1, 'default_enabled': True},
        {'name': 'heavy', 'order': 2, 'default_enabled': True},
    ]

    def test_atomic_state_repairs_missing_compatibility_files_without_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            prepare.app_selection.save_selection(base, self.manifest, ['core'], [])
            # Missing and stale compatibility copies must both be repaired
            # from the committed state rather than from defaults.
            (base / 'installed-apps.txt').write_text('heavy\n')
            (base / 'enabled-apps.txt').unlink()
            with patch.object(prepare, 'BASE', base):
                self.assertTrue(prepare.synchronize_selection_copies(self.manifest))
            self.assertEqual(prepare.app_selection.read_names(base / 'installed-apps.txt'), ['core'])
            self.assertEqual(prepare.app_selection.read_names(base / 'enabled-apps.txt'), [])

    def test_legacy_install_keeps_default_compatibility_behavior(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with patch.object(prepare, 'BASE', base):
                self.assertFalse(prepare.synchronize_selection_copies(self.manifest))
            self.assertEqual(prepare.app_selection.read_names(base / 'installed-apps.txt'), ['core', 'heavy'])
            self.assertEqual(prepare.app_selection.read_names(base / 'enabled-apps.txt'), ['core', 'heavy'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
