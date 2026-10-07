import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('upgrade_tests', ROOT / 'outputs/Rassberi-PI5-Codes/scripts/upgrade-package.py')
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


def digest(value):
    return hashlib.sha256(value).hexdigest()


class UpgradePlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.stage = base / 'stage'
        self.target = base / 'target'
        self.stage.mkdir()
        self.target.mkdir()
        self.original_target = upgrade.TARGET
        upgrade.TARGET = self.target
        self.addCleanup(setattr, upgrade, 'TARGET', self.original_target)

    def test_known_previous_file_is_replaceable(self):
        old, new = b'previous\n', b'incoming\n'
        (self.stage / 'script.py').write_bytes(new)
        (self.target / 'script.py').write_bytes(old)
        changes, preserved = upgrade.plan(self.stage, {'script.py': {'previous_sha256': digest(old)}})
        self.assertEqual(changes[0]['action'], 'replace')
        self.assertEqual(preserved, [])

    def test_unknown_customized_file_is_preserved(self):
        (self.stage / 'script.py').write_bytes(b'incoming\n')
        (self.target / 'script.py').write_bytes(b'custom\n')
        changes, preserved = upgrade.plan(self.stage, {'script.py': {'previous_sha256': digest(b'previous\n')}})
        self.assertEqual(changes, [])
        self.assertEqual(preserved[0]['path'], 'script.py')

    def test_private_storage_and_env_are_never_candidates(self):
        (self.stage / 'configs').mkdir()
        (self.stage / 'compose/app').mkdir(parents=True)
        (self.stage / 'configs/storage.json').write_text('{}')
        (self.stage / 'compose/app/.env').write_text('SECRET=value')
        self.assertEqual(list(upgrade.files(self.stage)), [])

    def test_storage_role_preferences_are_preserved_across_upgrade(self):
        self.assertIn('configs/storage-preferences.json', upgrade.PROTECTED)

    def test_custom_selected_only_layout_stages_without_unselected_hdd_requirement(self):
        """Release staging must retain inactive paths on an SSD-only install."""
        source = Path(self.temporary.name) / 'incoming'
        shutil.copytree(ROOT / 'outputs/Rassberi-PI5-Codes', source,
                        ignore=shutil.ignore_patterns('__pycache__', 'logs', '.git'))
        manifest = [
            {'name': 'wanted', 'order': 1, 'directories': [
                {'path': '/srv/docker/appdata/wanted'}]},
            {'name': 'unselected-hdd', 'order': 2, 'mounts': ['hdd'], 'directories': [
                {'path': '/mnt/hdd/unselected'}]},
        ]
        (source / 'manifest.json').write_text(json.dumps(manifest))
        (self.target / 'configs').mkdir()
        (self.target / 'manifest.json').write_text(json.dumps(manifest))
        (self.target / 'configs/storage.json').write_text(json.dumps({
            'version': 2, 'devices': {'root': {'mount': '/', 'uuid': 'root-uuid', 'filesystem': 'ext4'}}
        }))
        (self.target / 'configs/layout.json').write_text(json.dumps({'placements': {
            '/srv/docker/appdata/wanted': '/srv/pi-data/appdata/wanted'
        }}))
        selection = importlib.util.spec_from_file_location('selection_for_upgrade_test',
                                                             source / 'scripts/app_selection.py')
        app_selection = importlib.util.module_from_spec(selection)
        selection.loader.exec_module(app_selection)
        app_selection.save_selection(self.target, manifest, ['wanted'], [])
        original_source = upgrade.SOURCE
        upgrade.SOURCE = source
        self.addCleanup(setattr, upgrade, 'SOURCE', original_source)
        temporary, stage = upgrade.prepared_source()
        self.addCleanup(temporary.cleanup)
        staged = json.loads((stage / 'manifest.json').read_text())
        apps = {app['name']: app for app in staged}
        self.assertEqual(apps['wanted']['directories'][0]['path'], '/srv/pi-data/appdata/wanted')
        self.assertEqual(apps['unselected-hdd']['directories'][0]['path'], '/mnt/hdd/unselected')
        self.assertEqual(apps['unselected-hdd']['mounts'], ['hdd'])

    def test_generated_custom_layout_hash_is_replaceable(self):
        """A canonical Release 6 file rendered for custom storage is not a local edit."""
        source = Path(self.temporary.name) / 'incoming'
        shutil.copytree(ROOT / 'outputs/Rassberi-PI5-Codes', source,
                        ignore=shutil.ignore_patterns('__pycache__', 'logs', '.git'))
        canonical_old = [{
            'name': 'wanted', 'order': 1, 'mounts': [], 'memory_mib': 10,
            'directories': [{'path': '/srv/docker/appdata/wanted'}],
        }]
        canonical_new = [{
            'name': 'wanted', 'order': 1, 'mounts': [], 'memory_mib': 20,
            'directories': [{'path': '/srv/docker/appdata/wanted'}],
        }]
        old_manifest = (json.dumps(canonical_old, indent=2) + '\n').encode()
        (source / 'manifest.json').write_text(json.dumps(canonical_new, indent=2) + '\n')
        canonical_old_compose = {
            'name': 'pi-wanted', 'services': {'wanted': {
                'labels': {'package-release': 'old'},
                'volumes': [{'type': 'bind', 'source': '/srv/docker/appdata/wanted', 'target': '/data'}],
            }},
        }
        canonical_new_compose = {
            'name': 'pi-wanted', 'services': {'wanted': {
                'labels': {'package-release': 'new'},
                'volumes': [{'type': 'bind', 'source': '/srv/docker/appdata/wanted', 'target': '/data'}],
            }},
        }
        old_compose = (json.dumps(canonical_old_compose, indent=2) + '\n').encode()
        wanted = source / 'compose/wanted'
        wanted.mkdir(exist_ok=True)
        (wanted / 'compose.yml').write_text(json.dumps(canonical_new_compose, indent=2) + '\n')
        (self.target / 'configs').mkdir()
        storage = {'version': 2, 'devices': {
            'root': {'mount': '/', 'uuid': 'root-uuid', 'filesystem': 'ext4'},
        }}
        (self.target / 'configs/storage.json').write_text(json.dumps(storage))
        (self.target / 'configs/layout.json').write_text(json.dumps({'placements': {
            '/srv/docker/appdata/wanted': '/srv/pi-data/appdata/wanted',
        }}))
        custom_old = json.loads(old_manifest)
        custom_old[0]['directories'][0]['path'] = '/srv/pi-data/appdata/wanted'
        (self.target / 'manifest.json').write_text(json.dumps(custom_old, indent=2) + '\n')
        custom_old_compose = json.loads(old_compose)
        custom_old_compose['services']['wanted']['volumes'][0]['source'] = '/srv/pi-data/appdata/wanted'
        destination = self.target / 'compose/wanted/compose.yml'
        destination.parent.mkdir(parents=True)
        destination.write_text(json.dumps(custom_old_compose, indent=2) + '\n')
        selection_spec = importlib.util.spec_from_file_location('selection_for_reverse_layout_test',
                                                                  source / 'scripts/app_selection.py')
        selection = importlib.util.module_from_spec(selection_spec)
        selection_spec.loader.exec_module(selection)
        selection.save_selection(self.target, canonical_new, ['wanted'], [])
        original_source = upgrade.SOURCE
        upgrade.SOURCE = source
        self.addCleanup(setattr, upgrade, 'SOURCE', original_source)
        temporary, stage = upgrade.prepared_source()
        self.addCleanup(temporary.cleanup)
        changes, preserved = upgrade.plan(stage, {
            'manifest.json': {'accepted_sha256': [digest(old_manifest)]},
            'compose/wanted/compose.yml': {'accepted_sha256': [digest(old_compose)]},
        })
        changed = {row['path'] for row in changes}
        preserved_paths = {row['path'] for row in preserved}
        self.assertIn('manifest.json', changed)
        self.assertIn('compose/wanted/compose.yml', changed)
        self.assertNotIn('manifest.json', preserved_paths)
        self.assertNotIn('compose/wanted/compose.yml', preserved_paths)


if __name__ == '__main__':
    unittest.main()
