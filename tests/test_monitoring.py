import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path('outputs/Rassberi-PI5-Codes')

def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value
    spec.loader.exec_module(value)
    return value

proxy=module('heal_guard', ROOT/'configs/autoheal/guard-proxy.py')
diun=module('diun_prepare',ROOT/'compose/diun/prepare.py')
sys.path.insert(0, str((ROOT/'scripts').resolve()))
devices=module('monitor_devices',ROOT/'scripts/monitoring_devices.py')
MOUNTS='1 0 259:2 / / rw - ext4 /dev/nvme0n1p2 rw\n2 1 8:1 / /mnt/hdd rw - ext4 /dev/example rw\n3 1 179:1 / /mnt/media rw - ext4 /dev/mmcblk0p1 rw\n'

def container():
    return {'Config':{'Labels':{'pi.autoheal.nvme':'true','com.docker.compose.project':'pi-homebox'}},
            'State':{'Status':'running'},'HostConfig':{},'Mounts':[{'Type':'bind','Source':'/srv/docker/appdata/homebox','RW':True}]}

class AutohealSafety(unittest.TestCase):
    def test_nvme_opt_in(self):
        self.assertTrue(proxy.eligible(container(),MOUNTS))
    def test_unlabeled_refused(self):
        c=container();c['Config']['Labels'].pop('pi.autoheal.nvme');self.assertFalse(proxy.eligible(c,MOUNTS))
    def test_stopped_refused(self):
        c=container();c['State']['Status']='exited';self.assertFalse(proxy.eligible(c,MOUNTS))
    def test_hdd_refused_even_with_label(self):
        c=container();c['Mounts'][0]['Source']='/mnt/hdd/Nextcloud';self.assertFalse(proxy.eligible(c,MOUNTS))
    def test_readonly_media_refused(self):
        c=container();c['Mounts'].append({'Type':'bind','Source':'/mnt/media/Music','RW':False});self.assertFalse(proxy.eligible(c,MOUNTS))
    def test_disk_mounted_below_system_path_refused(self):
        extra=MOUNTS+'4 1 8:1 / /srv/docker/appdata/homebox rw - ext4 /dev/example rw\n'
        self.assertFalse(proxy.eligible(container(),extra))
    def test_device_refused(self):
        c=container();c['HostConfig']['Devices']=[{'PathOnHost':'/dev/nvme0'}];self.assertFalse(proxy.eligible(c,MOUNTS))
    def test_named_volume_refused(self):
        c=container();c['Mounts'][0]['Type']='volume';self.assertFalse(proxy.eligible(c,MOUNTS))
    def test_controller_cannot_heal_itself(self):
        c=container();c['Config']['Labels']['com.docker.compose.project']='pi-autoheal';self.assertFalse(proxy.eligible(c,MOUNTS))
    def test_invalid_host_mount_identity_fails(self):
        with self.assertRaises(ValueError):proxy.eligible(container(),'')

class ImageWatching(unittest.TestCase):
    def test_explicit_tag(self):
        self.assertEqual(diun.source_tag({'source_tag':'example/app:stable','image':'example/app@sha256:123'}),'example/app:stable')
    def test_legacy_evidence(self):
        self.assertEqual(diun.source_tag({'evidence':'OCI index verified; Source tag: sample/app:lts'}),'sample/app:lts')
    def test_registry_source(self):
        self.assertEqual(diun.source_tag({'source':'https://registry-1.docker.io/v2/user/app/manifests/4'}),'docker.io/user/app:4')
    def test_digest_only_not_watched(self):
        self.assertIsNone(diun.source_tag({'source':'https://ghcr.io/v2/user/app/manifests/sha256:abcd'}))
    def test_deduplication(self):
        manifest=[{'name':n,'images':[{'source_tag':'sample/app:4'}]} for n in ['one','two']]
        self.assertEqual(len(diun.make_images(manifest)),1)

class MonitoringContracts(unittest.TestCase):
    def test_api_proxies_never_published(self):
        for app, name in [('docker-socket-proxy','docker-socket-proxy'),('autoheal','autoheal-proxy'),('beszel','beszel-proxy')]:
            cfg=json.loads((ROOT/'compose'/app/'compose.yml').read_text())
            self.assertFalse(cfg['services'][name].get('ports'))
    def test_consumers_have_no_real_docker_socket(self):
        for app, names in [('autoheal',['autoheal']),('beszel',['beszel','beszel-agent']),('diun',['diun'])]:
            cfg=json.loads((ROOT/'compose'/app/'compose.yml').read_text())
            for name in names:
                self.assertFalse(any(v.get('source')=='/var/run/docker.sock' for v in cfg['services'][name].get('volumes',[])))
    def test_block_mount_defaults_never_guess_usb_letters(self):
        for app in ['beszel','scrutiny']:
            cfg=json.loads((ROOT/'compose'/app/'compose.yml').read_text())
            for service in cfg['services'].values():self.assertFalse(service.get('devices'))
    def test_missing_optional_disk_does_not_break_cpu_monitoring(self):
        cfg={'devices':{'root':{'mount':'/'},'hdd':{'mount':'/mnt/hdd'}}}
        def checked(*args,**kwargs):
            if kwargs['required']==['hdd']:raise RuntimeError('wrong UUID')
            return []
        with patch.object(devices.guard,'load_config',return_value=cfg),patch.object(devices.guard,'device_map',return_value=cfg['devices']),patch.object(devices.guard,'check',side_effect=checked),patch.object(devices.guard,'mounted',return_value={'source':'/dev/nvme0n1p2'}),patch.object(devices,'physical_disk',return_value=(Path('/dev/nvme0n1'),'')),patch.object(devices,'stable_source',return_value='/dev/disk/by-id/nvme-test'):
            rows=devices.discovered()
        self.assertEqual([r['key'] for r in rows],['root'])
    def test_same_physical_disk_not_duplicated(self):
        cfg={'devices':{'root':{'mount':'/'},'data':{'mount':'/mnt/data'}}}
        with patch.object(devices.guard,'load_config',return_value=cfg),patch.object(devices.guard,'device_map',return_value=cfg['devices']),patch.object(devices.guard,'check',return_value=[]),patch.object(devices.guard,'mounted',return_value={'source':'/dev/nvme0n1p2'}),patch.object(devices,'physical_disk',return_value=(Path('/dev/nvme0n1'),'')),patch.object(devices,'stable_source',return_value='/dev/disk/by-id/nvme-test'):
            self.assertEqual(len(devices.discovered()),1)

if __name__=='__main__':unittest.main()
