import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'outputs/Rassberi-PI5-Codes/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('storage_watch_tests', SCRIPTS / 'storage-watch.py')
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


class StorageWatchTests(unittest.TestCase):
    def test_resumed_container_gets_its_saved_restart_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'scripts').mkdir()
            (base / 'configs').mkdir()
            (base / 'scripts/storage_guard.py').write_text(
                'def selected_manifest(*args): return [{"name": "example", "directories": []}]\n'
                'def inspect_storage(*args, **kwargs): return []\n'
                'def app_requirements(app): return []\n'
                'def check(*args, **kwargs): return None\n'
            )
            paused = base / 'configs/storage-paused.json'
            paused.write_text(json.dumps([{
                'id': 'container-id', 'name': 'example-web', 'app': 'example', 'service': 'web',
                'reason': [], 'restart': {'Name': 'unless-stopped', 'MaximumRetryCount': 0},
            }]))
            container = {
                'Id': 'container-id', 'Name': '/example-web',
                'State': {'Status': 'exited'},
                'Config': {'Labels': {'com.docker.compose.project': 'pi-example',
                                      'com.docker.compose.service': 'web'}},
            }
            calls = []

            def fake_run(args, **kwargs):
                calls.append(args)
                if args == ['docker', 'ps', '-aq']:
                    return subprocess.CompletedProcess(args, 0, stdout='container-id\n')
                if args[:2] == ['docker', 'inspect']:
                    return subprocess.CompletedProcess(args, 0, stdout=json.dumps([container]))
                return subprocess.CompletedProcess(args, 0, stdout='')

            fake_fcntl = types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *args: None)
            with patch.object(watch, 'BASE', base), \
                 patch.object(watch, 'PAUSED', paused), \
                 patch.object(watch, 'LOCK', base / 'pi-server.lock'), \
                 patch.object(watch.os, 'geteuid', return_value=0, create=True), \
                 patch.object(watch.subprocess, 'run', side_effect=fake_run), \
                 patch.dict(sys.modules, {'fcntl': fake_fcntl}):
                self.assertEqual(watch.main(), 0)

            self.assertIn(['docker', 'update', '--restart=unless-stopped', 'container-id'], calls)
            self.assertIn(['docker', 'start', 'container-id'], calls)
            self.assertFalse(paused.exists())


if __name__ == '__main__':
    unittest.main()
