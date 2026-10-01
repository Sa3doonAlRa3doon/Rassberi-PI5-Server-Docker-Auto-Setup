"""Fixture tests: run on Windows or Linux without Docker or real drive mutations."""
import copy
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'outputs/Rassberi-PI5-Codes'
sys.path.insert(0, str(ROOT / 'scripts'))


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


backup = module('portable_backup', 'portable-backup.py')
tailscale = module('tailscale_setup', 'setup-tailscale-homepage.py')
diun_spec = importlib.util.spec_from_file_location('diun_prepare', ROOT / 'compose/diun/prepare.py')
diun = importlib.util.module_from_spec(diun_spec)
diun_spec.loader.exec_module(diun)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = self.root / 'snapshot'
        self.snapshot.mkdir()
        file = self.snapshot / 'files/mnt/hdd/Books/readme.txt'
        file.parent.mkdir(parents=True)
        file.write_bytes(b'Portable book bytes\n')
        self.row = {'path': '/mnt/hdd/Books/readme.txt', 'type': 'file', 'mode': 0o640,
                    'uid': 1000, 'gid': 1000, 'mtime_ns': 1000000000, 'atime_ns': 1000000000,
                    'size': file.stat().st_size, 'xattrs': {}, 'stored': 'files/mnt/hdd/Books/readme.txt',
                    'sha256': backup.sha256(file)}
        self.rows = [self.row]
        (self.snapshot / 'databases').mkdir()
        for name in ['manifest.json', 'plan.json', 'resume.json', 'original-containers.json']:
            (self.snapshot / name).write_text('{}')
        self.info = {'format': backup.FORMAT, 'files': 1, 'databases': [],
                     'created_utc': '20260929T000000Z', 'source_roots': ['/mnt/hdd/Books'], 'include_bulk': True}
        self.index()

    def tearDown(self):
        self.temp.cleanup()

    def index(self):
        (self.snapshot / 'backup.json').write_text(json.dumps(self.info))
        (self.snapshot / 'metadata.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in self.rows))
        checksums = {p.relative_to(self.snapshot).as_posix(): backup.sha256(p)
                     for p in self.snapshot.rglob('*') if p.is_file() and p.name not in {'COMPLETE', 'checksums.json'}}
        (self.snapshot / 'checksums.json').write_text(json.dumps(checksums))
        (self.snapshot / 'COMPLETE').write_text(json.dumps({'format': backup.FORMAT,
                      'checksums_sha256': backup.sha256(self.snapshot / 'checksums.json')}))

    def test_verify_plain_snapshot(self):
        self.assertTrue(backup.verify(self.snapshot)['verified'])

    def test_corrupt_file_rejected(self):
        (self.snapshot / self.row['stored']).write_text('bad')
        with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
            backup.verify(self.snapshot)

    def test_completion_checksum_rejected(self):
        (self.snapshot / 'checksums.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'completion marker'):
            backup.verify(self.snapshot)

    def test_extra_nested_complete_is_not_ignored(self):
        (self.snapshot / 'databases/COMPLETE').write_text('unindexed')
        with self.assertRaisesRegex(RuntimeError, 'unindexed'):
            backup.verify(self.snapshot)

    def test_metadata_traversal_rejected(self):
        self.rows[0]['path'] = '/mnt/hdd/../../etc/passwd'
        self.index()
        with self.assertRaisesRegex(RuntimeError, 'Unsafe original'):
            backup.verify(self.snapshot)

    def test_checksum_traversal_rejected(self):
        (self.root / 'outside').write_text('outside')
        index = backup.read_json(self.snapshot / 'checksums.json')
        index['../outside'] = backup.sha256(self.root / 'outside')
        (self.snapshot / 'checksums.json').write_text(json.dumps(index))
        with self.assertRaisesRegex(RuntimeError, 'Unsafe relative'):
            backup.verify(self.snapshot, require_complete=False)

    def test_duplicate_metadata_rejected(self):
        self.rows.append(copy.deepcopy(self.row))
        self.index()
        with self.assertRaisesRegex(RuntimeError, 'Duplicate original'):
            backup.verify(self.snapshot)

    def test_database_dump_required(self):
        self.info['databases'] = [{'status': 'dumped', 'file': 'databases/missing.sql'}]
        self.index()
        with self.assertRaisesRegex(RuntimeError, 'Database dump is absent'):
            backup.verify(self.snapshot)

    def test_restore_plan_does_not_create_files(self):
        target = self.root / 'new-stage'
        result = backup.restore_plan(self.snapshot, target)
        self.assertFalse(target.exists())
        self.assertIn('files', result['map'][0]['staged'])

    def test_staging_copies_bytes_and_retains_link_metadata(self):
        link = {**self.row, 'path': '/mnt/hdd/Books/external', 'type': 'symlink', 'target': '/etc/passwd'}
        self.rows.append(link)
        self.index()
        stage = self.root / 'stage'
        stage.mkdir()
        with patch.object(backup, 'restore_metadata') as metadata:
            held = backup.stage_files(self.snapshot, stage)
            metadata.assert_called_once()
        self.assertEqual((stage / self.row['stored']).read_bytes(), b'Portable book bytes\n')
        self.assertFalse((stage / 'files/mnt/hdd/Books/external').exists())
        self.assertEqual(held[0]['target'], '/etc/passwd')

    def test_staging_never_overwrites(self):
        stage = self.root / 'stage'
        original = stage / self.row['stored']
        original.parent.mkdir(parents=True)
        original.write_text('preserve me')
        with patch.object(backup, 'restore_metadata'), self.assertRaises(FileExistsError):
            backup.stage_files(self.snapshot, stage)
        self.assertEqual(original.read_text(), 'preserve me')

    def test_missing_configuration_plan_does_not_run_commands(self):
        with patch.object(backup, 'output', side_effect=AssertionError('must not execute')):
            result = backup.make_plan(dict(backup.DEFAULT))
        self.assertFalse(result['ready'])

    def test_symlink_checksum_rejected(self):
        link = self.snapshot / 'databases/symlink'
        try:
            link.symlink_to(self.snapshot / 'manifest.json')
        except OSError:
            self.skipTest('Host does not permit symlink creation')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            backup.verify(self.snapshot)


class RestartTests(unittest.TestCase):
    def container(self, identifier, service):
        return {'Id': identifier, 'Config': {'Labels': {'com.docker.compose.project': 'pi-example',
                'com.docker.compose.service': service}}}

    def test_exact_original_ids_backend_first(self):
        original = [self.container('app-id', 'app'), self.container('db-id', 'db')]
        with patch.object(backup, 'run') as calls, patch.object(backup, 'guard_app'), patch.object(backup, 'wait_ready'):
            errors = backup.resume(original, {'temporary-db'}, ROOT)
        self.assertFalse(errors)
        self.assertEqual([call.args[0] for call in calls.call_args_list],
                         [['docker', 'stop', '-t', '120', 'temporary-db'],
                          ['docker', 'start', 'db-id'], ['docker', 'start', 'app-id']])

    def test_guard_failure_leaves_apps_stopped(self):
        with patch.object(backup, 'run') as calls, patch.object(backup, 'guard_app', side_effect=RuntimeError('wrong UUID')):
            errors = backup.resume([self.container('app-id', 'app')], set(), ROOT)
        self.assertIn('wrong UUID', errors[0])
        calls.assert_not_called()

    def test_physical_disk_ancestors_resolved(self):
        tree = {'blockdevices': [{'name': '/dev/mapper/volume', 'type': 'crypt', 'children': [
                {'name': '/dev/sdc1', 'type': 'part', 'children': [{'name': '/dev/sdc', 'type': 'disk'}]}]}]}
        with patch.object(backup, 'output', return_value=json.dumps(tree)), patch.object(backup.os.path, 'realpath', side_effect=lambda x: x):
            self.assertEqual(backup.physical_disks('/dev/mapper/volume'), {'/dev/sdc'})

    def test_failure_keeps_partial_and_resumes_exact_originals(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'manifest.json').write_text('[]')
            original = self.container('app-id', 'app')
            original['State'] = {'Running': True, 'Status': 'running'}
            plan = {'ready': True, 'sources': [], 'warnings': []}
            with patch.object(backup, 'require_root'), patch.object(backup, 'server_lock', return_value=nullcontext()), \
                 patch.object(backup, 'make_plan', return_value=plan), \
                 patch.object(backup, 'inventory', side_effect=[[original], []]), \
                 patch.object(backup, 'pinned_folder', return_value=nullcontext((base, {}))), \
                 patch.object(backup, 'run'), patch.object(backup, 'dump_databases', return_value=[]), \
                 patch.object(backup, 'containers', return_value=[]), \
                 patch.object(backup, 'copy_sources', side_effect=RuntimeError('disk disappeared')), \
                 patch.object(backup, 'resume', return_value=[]) as resume:
                with self.assertRaisesRegex(RuntimeError, 'disk disappeared'):
                    backup.create(dict(backup.DEFAULT), base)
            resume.assert_called_once_with([original], set(), base)
            partial = list(base.glob('incomplete-*'))
            self.assertEqual(len(partial), 1)
            self.assertFalse((partial[0] / 'COMPLETE').exists())
            self.assertTrue((partial[0] / 'resume.json').is_file())

    def test_restart_detection_preserves_partial_and_resumes_originals(self):
        """A writer that comes back after Docker stop must prevent a file copy."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'manifest.json').write_text('[]')
            original = self.container('app-id', 'app')
            original['State'] = {'Running': True, 'Status': 'running'}
            plan = {'ready': True, 'sources': [], 'warnings': []}
            with patch.object(backup, 'require_root'), patch.object(backup, 'server_lock', return_value=nullcontext()), \
                 patch.object(backup, 'make_plan', return_value=plan), \
                 patch.object(backup, 'inventory', side_effect=[[original], [original]]), \
                 patch.object(backup, 'pinned_folder', return_value=nullcontext((base, {}))), \
                 patch.object(backup, 'run'), patch.object(backup, 'dump_databases', return_value=[]), \
                 patch.object(backup, 'copy_sources') as copy_sources, \
                 patch.object(backup, 'resume', return_value=[]) as resume:
                with self.assertRaisesRegex(RuntimeError, 'managed container restarted'):
                    backup.create(dict(backup.DEFAULT), base)
            copy_sources.assert_not_called()
            resume.assert_called_once_with([original], set(), base)
            partial = list(base.glob('incomplete-*'))
            self.assertEqual(len(partial), 1)
            self.assertFalse((partial[0] / 'COMPLETE').exists())
            self.assertTrue((partial[0] / 'resume.json').is_file())

    def test_remapped_database_and_appdata_keep_their_kinds(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'configs').mkdir()
            placements = {'/srv/docker/databases/test': '/mnt/ssd/PiServer/db/test',
                          '/srv/docker/appdata/test': '/mnt/ssd/PiServer/state/test',
                          '/mnt/hdd/Books': '/mnt/large/PiServer/Books'}
            (base / 'configs/layout.json').write_text(json.dumps({'placements': placements}))
            app = {'name': 'test', 'database': {'type': 'postgres', 'path': '/mnt/ssd/PiServer/db/test'},
                   'directories': [{'path': value} for value in placements.values()]}
            groups = {r['path']: r['kind'] for r in backup.data_groups(base, [app])}
            self.assertEqual(groups, {'/mnt/ssd/PiServer/db/test': 'database',
                                     '/mnt/ssd/PiServer/state/test': 'appdata',
                                     '/mnt/large/PiServer/Books': 'bulk'})
            with patch.object(backup.Path, 'exists', return_value=True), \
                 patch.object(backup.Path, 'is_dir', return_value=True), \
                 patch.object(backup, 'no_symlink'):
                sources = backup.source_list(base, [app], {}, False)
            paths = {path.as_posix() for path in sources}
            self.assertIn('/mnt/ssd/PiServer/state/test', paths)
            self.assertNotIn('/mnt/ssd/PiServer/db/test', paths)
            self.assertNotIn('/mnt/large/PiServer/Books', paths)
            self.assertNotIn('/mnt/ssd', paths)

    def test_absent_sql_container_rechecks_selected_storage_before_uninitialized(self):
        """A disappeared custom database mount must never be called empty."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            database = base / 'external-ssd' / 'database'
            app = {
                'name': 'example',
                'database': {'type': 'postgres', 'name': 'example', 'user': 'example',
                             'service': 'db', 'path': str(database)},
                'directories': [{'path': str(database)}],
            }
            with patch.object(backup, 'guard_app', side_effect=RuntimeError('custom SSD is not mounted')) as guarded:
                with self.assertRaisesRegex(RuntimeError, 'not mounted'):
                    backup.dump_databases([app], [], base / 'dumps', set(), base)
            guarded.assert_called_once_with(base, 'example')


class BackupSelectionTests(unittest.TestCase):
    class Guard:
        @staticmethod
        def device_map(config):
            return config

        @staticmethod
        def path_key(path, config):
            for key, root in sorted(config.items(), key=lambda row: len(row[1]), reverse=True):
                if root == '/' and path.startswith('/'):
                    return key
                if path == root or path.startswith(root + '/'):
                    return key
            raise RuntimeError('retired storage path')

    def test_atomic_selection_file_is_used_without_legacy_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'configs').mkdir()
            ssd = base / 'ssd'
            hdd = base / 'hdd'
            ssd.mkdir(); hdd.mkdir()
            (base / 'configs/app-selection.json').write_text(json.dumps({
                'version': 1, 'installed': ['ssd-app'], 'startup': []
            }))
            manifest = [
                {'name': 'ssd-app', 'order': 1, 'directories': [{'path': str(ssd)}]},
                {'name': 'hdd-app', 'order': 2, 'directories': [{'path': str(hdd)}]},
            ]
            active, selected, historical, unavailable = backup.backup_manifest(
                base, manifest, {'root': str(ssd)}, self.Guard())
            self.assertEqual([app['name'] for app in active], ['ssd-app'])
            self.assertEqual(selected, ['ssd-app'])
            self.assertEqual(historical, [])
            self.assertEqual(unavailable, [])

    def test_historical_env_never_readds_retired_database_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'configs').mkdir()
            (base / 'installed-apps.txt').write_text('current\n')
            (base / 'compose/old').mkdir(parents=True)
            (base / 'compose/old/.env').write_text('EXAMPLE=1\n')
            root = base / 'root'
            retired = base / 'retired'
            root.mkdir(); retired.mkdir()
            manifest = [
                {'name': 'current', 'order': 1, 'directories': [{'path': str(root / 'current')}]},
                {'name': 'old', 'order': 2,
                 'database': {'type': 'postgres', 'path': str(retired / 'db')},
                 'directories': [{'path': str(retired / 'state')}]},
            ]
            active, _, historical, unavailable = backup.backup_manifest(
                base, manifest, {'root': str(root)}, self.Guard())
            old = next(app for app in active if app['name'] == 'old')
            self.assertEqual(historical, ['old'])
            self.assertIsNone(old['database'])
            self.assertNotIn(str(retired / 'db'),
                             {row['path'] for row in backup.data_groups(base, active)})
            self.assertIn(('old', str(retired / 'db')), unavailable)

    def test_backup_checks_only_devices_backing_selected_or_retained_data(self):
        manifest = [
            {'name': 'root-app', 'directories': [{'path': '/srv/docker/appdata/root-app'}]},
            {'name': 'hdd-app', 'directories': [{'path': '/mnt/hdd/Files'}]},
        ]
        storage = {'root': '/', 'hdd': '/mnt/hdd', 'retired-media': '/mnt/media'}
        keys = backup.backup_storage_keys(backup.data_groups(Path('/tmp'), manifest), storage, self.Guard())
        self.assertEqual(keys, ['root', 'hdd'])

    def test_missing_selected_directory_is_a_backup_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            missing = base / 'missing'
            app = {'name': 'selected', 'directories': [{'path': str(missing)}]}
            with self.assertRaisesRegex(RuntimeError, 'Required selected or retained backup directory is missing'):
                backup.source_list(base, [app], {}, True)


class TailscaleTests(unittest.TestCase):
    def setUp(self):
        self.host = 'pi.example.ts.net'
        self.route = {'app': 'homebox', 'port': 17745, 'target': 'http://192.168.1.2:7745'}
        self.key = self.host + ':17745'
        self.exact = {'TCP': {'17745': {'HTTPS': True}},
                      'Web': {self.key: {'Handlers': {'/': {'Proxy': self.route['target']}}}}}

    def test_exact_private_route_reusable(self):
        self.assertIsNone(tailscale.conflict(self.exact, self.route, self.host))

    def test_existing_different_target_refused(self):
        self.exact['Web'][self.key]['Handlers']['/']['Proxy'] = 'http://127.0.0.1:9999'
        self.assertIn('not be overwritten', tailscale.conflict(self.exact, self.route, self.host))

    def test_funnel_route_refused(self):
        self.exact['AllowFunnel'] = {self.key: True}
        self.assertIn('Funnel', tailscale.conflict(self.exact, self.route, self.host))

    def test_other_paths_not_replaced(self):
        self.exact['Web'][self.key]['Handlers']['/keep'] = {'Text': 'preserve'}
        self.assertIsNotNone(tailscale.conflict(self.exact, self.route, self.host))

    def test_foreground_route_refused(self):
        self.assertIn('foreground', tailscale.conflict({'Foreground': {'session': self.exact}}, self.route, self.host))

    def test_ports_map_to_actual_app_listener_and_skip_proxy(self):
        info = {'ipv4': '100.70.80.90', 'hostname': self.host, 'local_ipv4': ['192.168.1.2', '100.70.80.90']}
        apps = [{'name': 'homebox', 'ports': [{'host': 7745, 'scheme': 'http'}]},
                {'name': 'docker-socket-proxy', 'ports': [{'host': 2375, 'scheme': 'http'}]}]
        with patch.object(tailscale, 'read_env', return_value={'BIND_IP': '192.168.1.2'}):
            routes = tailscale.routes(apps, info)
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[1]['target'], 'http://192.168.1.2:7745')
        self.assertEqual(routes[1]['url'], 'https://pi.example.ts.net:17745/')

    def test_tailscale_uses_only_saved_install_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest = [
                {'name': 'homepage-tailscale', 'order': 1},
                {'name': 'chosen', 'order': 2},
                {'name': 'unselected', 'order': 3},
            ]
            (base / 'manifest.json').write_text(json.dumps(manifest))
            tailscale.app_selection.save_selection(base, manifest,
                                                   ['homepage-tailscale', 'chosen'], [])
            self.assertEqual([app['name'] for app in tailscale.installed_manifest(base)],
                             ['homepage-tailscale', 'chosen'])


class DiunTests(unittest.TestCase):
    def test_diun_watches_only_saved_application_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest = [
                {'name': 'chosen', 'order': 1, 'images': [{'source_tag': 'example/chosen:stable'}]},
                {'name': 'unselected', 'order': 2, 'images': [{'source_tag': 'example/unselected:stable'}]},
            ]
            tailscale.app_selection.save_selection(base, manifest, ['chosen'], [])
            watched = diun.make_images(diun.installed_manifest(base, manifest))
        self.assertEqual([row['name'] for row in watched], ['example/chosen:stable'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
