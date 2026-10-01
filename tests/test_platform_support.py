import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'outputs/Rassberi-PI5-Codes/scripts/platform_check.py'
spec = importlib.util.spec_from_file_location('platform_check_tests', SCRIPT)
platform_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform_check)


class PlatformSupportTests(unittest.TestCase):
    def test_supported_debian_family_arm64_hosts(self):
        for release in ({'ID': 'raspbian', 'ID_LIKE': 'debian'},
                        {'ID': 'debian'},
                        {'ID': 'ubuntu', 'ID_LIKE': 'debian'},
                        {'ID': 'linuxmint', 'ID_LIKE': 'ubuntu debian'}):
            result = platform_check.validate('Linux', 'aarch64', release)
            self.assertEqual(result['system'], 'Linux')

    def test_x86_and_non_debian_hosts_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'ARM64'):
            platform_check.validate('Linux', 'x86_64', {'ID': 'ubuntu', 'ID_LIKE': 'debian'})
        with self.assertRaisesRegex(RuntimeError, 'Debian-family'):
            platform_check.validate('Linux', 'arm64', {'ID': 'fedora', 'ID_LIKE': 'fedora'})

    def test_os_release_is_parsed_without_sourcing_shell_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'os-release'
            path.write_text('ID="ubuntu"\nID_LIKE="debian"\nUNTRUSTED=$(echo no)\n')
            release = platform_check.os_release(path)
        self.assertEqual(release['ID'], 'ubuntu')
        self.assertEqual(release['ID_LIKE'], 'debian')
        self.assertEqual(release['UNTRUSTED'], '$(echo')

    def test_installer_uses_platform_preflight_not_a_tied_release_codename(self):
        installer = (ROOT / 'outputs/Rassberi-PI5-Codes/install-all.sh').read_text()
        setup = (ROOT / 'outputs/Rassberi-PI5-Codes/setup-server.sh').read_text()
        upgrade = (ROOT / 'outputs/Rassberi-PI5-Codes/scripts/upgrade-package.py').read_text()
        migration = (ROOT / 'outputs/Rassberi-PI5-Codes/scripts/apply-storage-update.py').read_text()
        self.assertIn('platform_check.py', installer)
        self.assertNotIn('VERSION_CODENAME', installer)
        self.assertIn('platform_check.py', setup)
        self.assertIn('validate_host()', upgrade)
        self.assertIn('validate_host()', migration)
        self.assertLess(installer.index('platform_check.py'), installer.index('mkdir -p "$SOURCE/logs"'))
        self.assertIn('DPkg::Lock::Timeout=300', installer)
        self.assertNotIn('set-timezone', installer)


if __name__ == '__main__':
    unittest.main(verbosity=2)
