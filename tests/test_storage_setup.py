import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'outputs/Rassberi-PI5-Codes/scripts'))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


storage = load('storage_setup_tests', 'outputs/Rassberi-PI5-Codes/scripts/storage_setup.py')
portable = load('portable_backup_tests', 'outputs/Rassberi-PI5-Codes/scripts/portable-backup.py')


class StorageLayoutTests(unittest.TestCase):
    def package(self, manifest, layout=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        (base / 'configs').mkdir()
        (base / 'compose').mkdir()
        (base / 'manifest.json').write_text(json.dumps(manifest))
        (base / 'configs/storage.json').write_text(json.dumps({
            'root': {'mount': '/', 'device': '/dev/nvme0n1p2', 'uuid': None, 'filesystem': 'ext4'},
            'hdd': {'mount': '/mnt/hdd', 'uuid': 'hdd-uuid', 'filesystem': 'ext4'},
            'media': {'mount': '/mnt/media', 'uuid': 'media-uuid', 'filesystem': 'ext4'}}))
        if layout:
            (base / 'configs/layout.json').write_text(json.dumps({'placements': layout}))
        return base

    def test_catalog_round_trip_maps_children_to_canonical_group(self):
        before = '/srv/docker/appdata/example'
        after = '/srv/pi-data/release/appdata/example'
        base = self.package([{'name': 'example', 'directories': [
            {'path': after}, {'path': after + '/nested'}]}], {before: after})
        rows = storage.catalog(base)
        self.assertEqual(rows, [{'id': before, 'current': after, 'apps': ['example'], 'kind': 'appdata'}])

    def test_catalog_can_limit_groups_to_installed_apps(self):
        base = self.package([
            {'name': 'wanted', 'directories': [{'path': '/srv/docker/appdata/wanted'}]},
            {'name': 'unselected', 'directories': [{'path': '/mnt/hdd/unused'}]},
        ])
        rows = storage.catalog(base, ['wanted'])
        self.assertEqual([row['id'] for row in rows], ['/srv/docker/appdata/wanted'])

    def test_plan_uses_only_selected_apps_with_selected_only_storage(self):
        """A fresh custom install must not require an unselected HDD app."""
        base = self.package([
            {'name': 'wanted', 'order': 1, 'mounts': [],
             'directories': [{'path': '/srv/docker/appdata/wanted'}]},
            {'name': 'unselected-hdd-app', 'order': 2, 'mounts': ['hdd'],
             'directories': [{'path': '/mnt/hdd/unselected'}]},
        ])
        (base / 'installed-apps.txt').write_text('wanted\n', encoding='utf-8')
        root = {'eligible': True, 'uuid': 'root-uuid', 'mount': '/', 'kind': 'SSD',
                'free_bytes': 10**12}

        with patch.object(storage, 'validate_destination', return_value=root):
            proposal = storage.plan(
                {'/srv/docker/appdata/wanted': '/srv/docker/appdata/wanted'}, base, [root])

        self.assertEqual(set(proposal['storage']['devices']), {'root'})
        apps = {app['name']: app for app in proposal['manifest']}
        self.assertEqual(apps['wanted']['mounts'], [])
        # The plan must neither rewrite nor validate data belonging to an app
        # that has not been selected for this fresh deployment.
        self.assertEqual(apps['unselected-hdd-app']['mounts'], ['hdd'])
        self.assertEqual(apps['unselected-hdd-app']['directories'][0]['path'], '/mnt/hdd/unselected')

    def test_apply_does_not_rewrite_an_unselected_app_child_path(self):
        """Moving selected data cannot silently change an inactive project's config."""
        source = '/srv/docker/appdata/wanted'
        target = '/srv/pi-data/custom/appdata/wanted'
        child = source + '/child'
        base = self.package([
            {'name': 'wanted', 'order': 1, 'mounts': [],
             'directories': [{'path': source}]},
            {'name': 'unselected', 'order': 2, 'mounts': [],
             'directories': [{'path': child}]},
        ])
        (base / 'installed-apps.txt').write_text('wanted\n', encoding='utf-8')
        for app, path in [('wanted', source), ('unselected', child)]:
            project = base / 'compose' / app
            project.mkdir()
            (project / 'compose.yml').write_text(json.dumps({
                'services': {'app': {'volumes': [
                    {'type': 'bind', 'source': path, 'target': '/data'}]}}
            }), encoding='utf-8')
        root = {'eligible': True, 'uuid': 'root-uuid', 'mount': '/', 'kind': 'SSD',
                'free_bytes': 10**12}

        with patch.object(storage, 'discover', return_value=[root]), \
             patch.object(storage, 'validate_destination', return_value=root):
            storage.apply({source: target}, base=base)

        wanted = json.loads((base / 'compose/wanted/compose.yml').read_text())
        unselected = json.loads((base / 'compose/unselected/compose.yml').read_text())
        self.assertEqual(wanted['services']['app']['volumes'][0]['source'], target)
        self.assertEqual(unselected['services']['app']['volumes'][0]['source'], child)

    def test_auto_select_supports_ssd_only_machine(self):
        disks = [{'eligible': True, 'uuid': 'ssd', 'mount': '/', 'kind': 'SSD', 'free_bytes': 10**12}]
        rows = [{'id': '/srv/docker/appdata/app', 'kind': 'appdata'},
                {'id': '/mnt/hdd/Shared', 'kind': 'bulk'}]
        result = storage.auto_select(disks, rows)
        self.assertTrue(all(path.startswith('/srv/pi-data/') for path in result.values()))
        self.assertNotIn('/mnt/hdd', ''.join(result.values()))

    def test_auto_select_excludes_backup_disk(self):
        disks = [
            {'eligible': True, 'uuid': 'ssd', 'mount': '/', 'kind': 'SSD', 'free_bytes': 10**12},
            {'eligible': True, 'uuid': 'backup', 'mount': '/mnt/backup', 'kind': 'HDD', 'free_bytes': 2*10**12}]
        rows = [{'id': '/mnt/hdd/Shared', 'kind': 'bulk'}]
        result = storage.auto_select(disks, rows, backup_uuid='backup')
        self.assertTrue(next(iter(result.values())).startswith('/srv/pi-data/'))

    def test_render_rewrites_bind_source_not_secret(self):
        base = self.package([])
        project = base / 'compose/example'
        project.mkdir()
        source = '/srv/docker/appdata/example'
        compose = {'services': {'app': {'volumes': [
            {'type': 'bind', 'source': source, 'target': '/data'}],
            'environment': {'PASSWORD': 'prefix-' + source}}}}
        (project / 'compose.yml').write_text(json.dumps(compose))
        (project / '.env').write_text('PASSWORD=prefix-' + source + '\nDATA_PATH=' + source + '\n')
        rendered = storage.render_files(base, {source: '/srv/pi-data/app'})
        changed = json.loads(rendered[project / 'compose.yml'])
        self.assertEqual(changed['services']['app']['volumes'][0]['source'], '/srv/pi-data/app')
        self.assertEqual(changed['services']['app']['environment']['PASSWORD'], 'prefix-' + source)
        env = rendered[project / '.env'].decode()
        self.assertIn('PASSWORD=prefix-' + source, env)
        self.assertIn('DATA_PATH=/srv/pi-data/app', env)

    def test_database_and_appdata_refuse_hdd(self):
        base = self.package([{'name': 'dbapp', 'directories': [
            {'path': '/srv/docker/databases/dbapp', 'uid': 999, 'gid': 999, 'mode': '0700'}]}])
        disks = [{'eligible': True, 'uuid': 'root', 'mount': '/', 'kind': 'SSD', 'free_bytes': 10**12},
                 {'eligible': True, 'uuid': 'hdd', 'mount': '/mnt/hdd', 'kind': 'HDD', 'free_bytes': 10**12}]
        with patch.object(storage, 'validate_destination', return_value=disks[1]):
            with self.assertRaisesRegex(RuntimeError, 'require SSD'):
                storage.plan({'/srv/docker/databases/dbapp': '/mnt/hdd/dbapp'}, base, disks)

    def test_successful_migration_restores_policy_to_recreated_container(self):
        """A Compose replacement receives the original restart intent by identity."""
        base = self.package([])
        (base / 'backups').mkdir()
        source = '/srv/docker/appdata/example'
        destination = str(base / 'moved-example')
        proposal = {
            'changes': [{'apps': ['example'], 'source': source, 'destination': destination,
                         'source_exists': False, 'populated': False, 'drive': 'root'}],
            'replacements': {source: destination},
            'selected_apps': ['example'],
            'manifest': [],
            'storage': {'version': 2, 'devices': {'root': {'mount': '/', 'uuid': 'root', 'filesystem': 'ext4'}}},
            'placements': {source: destination},
            'requires_copy': False,
        }
        container = {
            'Id': 'container-id',
            'State': {'Status': 'running'},
            'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped', 'MaximumRetryCount': 0}},
            'Config': {'Labels': {'com.docker.compose.project': 'pi-example',
                                  'com.docker.compose.service': 'web'}},
            'Mounts': [],
        }
        replacement = {**container, 'Id': 'replacement-id'}
        calls = []
        compose_started = False

        def fake_run(args, **kwargs):
            nonlocal compose_started
            calls.append(args)
            if args[:3] == ['docker', 'ps', '-aq']:
                return subprocess.CompletedProcess(args, 0,
                    stdout=('replacement-id\n' if compose_started else 'container-id\n'))
            if args[:2] == ['docker', 'inspect']:
                return subprocess.CompletedProcess(args, 0,
                    stdout=json.dumps([replacement if compose_started else container]))
            if args[:2] == ['docker', 'compose']:
                compose_started = True
            return subprocess.CompletedProcess(args, 0, stdout='')

        with patch.object(storage, 'plan', return_value=proposal), \
             patch.object(storage, 'deployed_layout', return_value=True), \
             patch.object(storage, 'render_files', return_value={}), \
             patch.object(storage, 'directory_owners', return_value={}), \
             patch.object(storage, 'run', side_effect=fake_run), \
             patch.object(storage.guard, 'check'), \
             patch.object(storage.guard, 'assert_path'):
            storage.apply({source: destination}, base=base)

        updates = [call for call in calls if call[:2] == ['docker', 'update']]
        self.assertEqual(updates[0], ['docker', 'update', '--restart=no', 'container-id'])
        self.assertIn(['docker', 'update', '--restart=unless-stopped', 'replacement-id'], updates)
        self.assertNotIn(['docker', 'update', '--restart=unless-stopped', 'container-id'], updates)


class PortableClassificationTests(unittest.TestCase):
    def test_embedded_database_directory_is_file_backed_up(self):
        manifest = [{'name': 'scrutiny', 'database': {'kind': 'application-embedded',
            'path': '/srv/docker/databases/scrutiny-influxdb'}, 'directories': [
            {'path': '/srv/docker/databases/scrutiny-influxdb'}]}]
        rows = portable.data_groups(Path('/srv/docker'), manifest)
        self.assertEqual(rows[0]['kind'], 'appdata')

    def test_postgres_raw_directory_is_logically_dumped(self):
        manifest = [{'name': 'nextcloud', 'database': {'type': 'postgres'}, 'directories': [
            {'path': '/srv/docker/databases/nextcloud'}]}]
        rows = portable.data_groups(Path('/srv/docker'), manifest)
        self.assertEqual(rows[0]['kind'], 'database')


if __name__ == '__main__':
    unittest.main()
