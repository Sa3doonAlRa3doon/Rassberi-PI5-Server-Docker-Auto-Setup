import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'outputs/Rassberi-PI5-Codes/scripts'))

from docker_restart import restart_policy_option


class DockerRestartPolicyTests(unittest.TestCase):
    def test_preserves_supported_policy_forms(self):
        self.assertEqual(restart_policy_option({'Name': 'no', 'MaximumRetryCount': 0}), 'no')
        self.assertEqual(restart_policy_option({'Name': 'always', 'MaximumRetryCount': 0}), 'always')
        self.assertEqual(restart_policy_option({'Name': 'unless-stopped', 'MaximumRetryCount': 0}), 'unless-stopped')
        self.assertEqual(restart_policy_option({'Name': 'on-failure', 'MaximumRetryCount': 5}), 'on-failure:5')

    def test_rejects_invalid_saved_policy(self):
        for policy in (None, {}, {'Name': 'shell;bad'}, {'Name': 'on-failure', 'MaximumRetryCount': '-1'}):
            with self.assertRaises(RuntimeError):
                restart_policy_option(policy)

    def test_storage_watcher_uses_the_saved_policy_on_resume(self):
        watcher = (ROOT / 'outputs/Rassberi-PI5-Codes/scripts/storage-watch.py').read_text(encoding='utf-8')
        self.assertIn("restart_policy_option(item.get('restart'))", watcher)
        self.assertIn("'--restart=' + restart_options[item['id']]", watcher)
        self.assertNotIn("'--restart=on-failure:5'", watcher)


if __name__ == '__main__':
    unittest.main()
