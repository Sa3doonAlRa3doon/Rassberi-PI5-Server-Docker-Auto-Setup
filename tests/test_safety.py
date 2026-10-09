import importlib.util
from pathlib import Path
import socket
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/'outputs/Rassberi-PI5-Codes'
def module(name):
    s=importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

guard=module('storage_guard'); manager=module('manage'); prepare=module('prepare')
HDD_UUID='a8293b36-2c0e-4852-84fd-92ac7503f4db'
REAL_STAT=guard.os.stat
MEDIA_UUID='17e44bc7-f360-45c4-878b-a7fe7aa45f6e'

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.rows={
          '/':dict(target='/',source='/dev/nvme0n1p2',fstype='ext4',uuid=None,options='rw,relatime'),
          '/mnt/hdd':dict(target='/mnt/hdd',source='/dev/replacement-partition',fstype='ext4',uuid=HDD_UUID,options='rw,relatime'),
          '/mnt/media':dict(target='/mnt/media',source='/dev/mmcblk0p1',fstype='ext4',uuid=MEDIA_UUID,options='rw,relatime')}
        self.free=types.SimpleNamespace(f_bavail=100*1024**3,f_bfree=100*1024**3,f_frsize=1,f_blocks=200*1024**3)
        def mounted(path):
            return self.rows[path]
        def containing(path):
            if str(path).startswith('/mnt/hdd'): return self.rows['/mnt/hdd']
            if str(path).startswith('/mnt/media'): return self.rows['/mnt/media']
            return self.rows['/']
        self.patches=[
            patch.object(guard,'mounted',side_effect=mounted),
            patch.object(guard,'containing_mount',side_effect=containing),
            patch.object(guard.os.path,'realpath',side_effect=lambda p:p),
            patch.object(guard.os.path,'exists',return_value=True),
            patch.object(guard.os,'statvfs',return_value=self.free,create=True),
            patch.object(guard.os,'stat',side_effect=lambda p, **kwargs: types.SimpleNamespace(st_dev=1 if str(p)=='/' else 2) if str(p) in {'/','/mnt/hdd','/mnt/media'} else REAL_STAT(p, **kwargs)),
        ]
        for p in self.patches: p.start(); self.addCleanup(p.stop)

    def check_all(self, minimum=False):
        return guard.check(required=['root','hdd','media'], minimum=minimum)

    def test_correct_storage_passes(self): self.assertEqual(len(self.check_all()),3)
    def test_absent_hdd_fails(self):
        self.rows['/mnt/hdd']['target']='/'
        with self.assertRaisesRegex(RuntimeError,'NOT MOUNTED'): self.check_all()
    def test_wrong_uuid_fails(self):
        self.rows['/mnt/media']['uuid']='WRONG'
        with self.assertRaisesRegex(RuntimeError,'WRONG UUID'): self.check_all()
    def test_read_only_fails(self):
        self.rows['/mnt/hdd']['options']='ro,relatime'
        with self.assertRaisesRegex(RuntimeError,'read-only'): self.check_all()
    def test_non_nvme_root_fails(self):
        self.rows['/']['source']='/dev/mmcblk0p2'
        with self.assertRaisesRegex(RuntimeError,'NVMe partition'): self.check_all()
    def test_critical_full_disk_fails(self):
        self.free.f_bavail=10*1024**3; self.free.f_bfree=10*1024**3
        with self.assertRaisesRegex(RuntimeError,'low space'): self.check_all()
    def test_install_requires_40gib(self):
        self.free.f_bavail=35*1024**3; self.free.f_bfree=35*1024**3; self.free.f_blocks=50*1024**3
        with self.assertRaisesRegex(RuntimeError,'low space'): self.check_all(minimum=True)
    def test_symlink_rejected(self):
        self.patches[2].stop()
        p=patch.object(guard.os.path,'realpath',side_effect=lambda value:'/different' if value=='/srv/docker' else value)
        p.start(); self.addCleanup(p.stop)
        with self.assertRaisesRegex(RuntimeError,'symlink'): self.check_all()
    def test_nested_mount_rejected(self):
        self.patches[1].stop()
        p=patch.object(guard,'containing_mount',side_effect=lambda path: self.rows['/mnt/hdd'] if str(path).startswith('/srv/docker') else self.rows['/'])
        p.start(); self.addCleanup(p.stop)
        with self.assertRaisesRegex(RuntimeError,'unexpected filesystem'): self.check_all()
    def test_old_uuid_is_not_the_expected_identity(self):
        self.assertNotIn('848dc06e-cb96-4103-a363-b0120c6755a3', (ROOT/'configs/storage.json').read_text())
    def test_database_locations_are_nvme_paths(self):
        import json
        for app in json.loads((ROOT/'manifest.json').read_text()):
            for directory in app.get('directories',[]):
                if '/databases/' in directory['path']:
                    self.assertTrue(directory['path'].startswith('/srv/docker/'))

    def test_every_application_declares_a_ram_planning_value(self):
        import json
        manifest = json.loads((ROOT/'manifest.json').read_text())
        self.assertTrue(manifest)
        for app in manifest:
            self.assertIsInstance(app.get('memory_mib'), int, app.get('name'))
            self.assertGreater(app['memory_mib'], 0, app.get('name'))

class HealthTests(unittest.TestCase):
    def test_unhealthy_is_failure(self):
        c={'Config':{'Labels':{'com.docker.compose.service':'app'}},'State':{'Status':'running','Health':{'Status':'unhealthy'}}}
        with patch.object(manager,'containers',return_value=[c]):
            with self.assertRaisesRegex(RuntimeError,'unhealthy'): manager.check_live('test',{'services':{'app':{}}},attempts=1)
    def test_running_no_probe_warns(self):
        c={'Config':{'Labels':{'com.docker.compose.service':'app'}},'State':{'Status':'running'}}
        with patch.object(manager,'containers',return_value=[c]):
            self.assertIn('no container healthcheck',manager.check_live('test',{'services':{'app':{}}},attempts=1)[0])
    def test_missing_is_failure(self):
        with patch.object(manager,'containers',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'missing'): manager.check_live('test',{'services':{'app':{}}},attempts=1)
    def test_port_collision(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1',0)); s.listen()
            cfg={'services':{'app':{'ports':[{'host_ip':'127.0.0.1','published':s.getsockname()[1]}]}}}
            with patch.object(manager,'containers',return_value=[]):
                with self.assertRaisesRegex(RuntimeError,'conflict'): manager.verify_ports('test',cfg)
    def test_existing_secret_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'.env'; p.write_text('SECRET=original\n')
            prepare.write_new(p,'SECRET=new\n')
            self.assertEqual(p.read_text(),'SECRET=original\n')

if __name__=='__main__': unittest.main(verbosity=2)
