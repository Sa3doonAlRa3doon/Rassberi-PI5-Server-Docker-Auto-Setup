import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'outputs/Rassberi-PI5-Codes'
if not PACKAGE.exists():
    PACKAGE = ROOT
spec = importlib.util.spec_from_file_location('app_passwords_tests', PACKAGE / 'scripts/app_passwords.py')
passwords = importlib.util.module_from_spec(spec)
spec.loader.exec_module(passwords)


class AppPasswordInventoryTests(unittest.TestCase):
    def test_inventory_lists_bootstrap_passwords_and_labels_internal_secrets(self):
        manifest = [{
            'name': 'demo', 'order': 1, 'secrets': ['ADMIN_PASSWORD', 'DB_PASSWORD'],
            'env': {'ADMIN_USER': 'saeed'},
            'ports': [{'host': 1234, 'scheme': 'http'}],
        }]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            env = base / 'compose/demo/.env'
            env.parent.mkdir(parents=True)
            env.write_text('ADMIN_USER=saeed\nADMIN_PASSWORD=login-secret\nDB_PASSWORD=db-secret\n')
            output = passwords.render_inventory(base, manifest, '192.168.1.50', generated_at='test-time')
            self.assertIn('Credential: login-secret', output)
            self.assertIn('Policy: FIRST_LOGIN_PASSWORD', output)
            self.assertIn('Credential: db-secret', output)
            self.assertIn('Policy: INTERNAL_SECRET', output)
            self.assertIn('Generated (UTC): test-time', output)
            self.assertIn('bootstrap values', output)

    def test_no_login_app_is_explicit(self):
        manifest = [{'name': 'frontend', 'order': 1, 'secrets': [], 'ports': []}]
        with tempfile.TemporaryDirectory() as temporary:
            output = passwords.render_inventory(Path(temporary), manifest, '192.168.1.50', generated_at='test-time')
        self.assertIn('Policy: NO_GENERATED_PASSWORD', output)
        self.assertIn('Create the account in the application first-run screen.', output)

    def test_inventory_is_root_only_and_replaced_atomically(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / passwords.INVENTORY_NAME
            passwords.write_inventory(path, 'secret\n')
            self.assertEqual(path.read_text(), 'secret\n')
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse((path.parent / ('.' + path.name + '.tmp')).exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
