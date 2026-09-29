#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess

def run(args):
    return subprocess.check_output(args, text=True).strip()

if __name__ == '__main__':
    info = json.loads(run(['docker','info','--format','{{json .}}']))
    if info.get('Architecture') not in ['aarch64','arm64']:
        raise SystemExit('CRITICAL: Docker daemon is not ARM64.')
    if info.get('LiveRestoreEnabled'):
        raise SystemExit('CRITICAL: Docker live-restore is enabled; disable it and restart Docker before installation so storage-loss shutdown can stop containers.')
    path = info['DockerRootDir']
    if run(['findmnt','-n','-o','TARGET','--target',os.path.realpath(path)]) != '/':
        raise SystemExit('CRITICAL: DockerRootDir must be on root NVMe: '+path)
    daemon = Path('/etc/docker/daemon.json')
    if daemon.exists() and json.loads(daemon.read_text()).get('live-restore', False):
        raise SystemExit('CRITICAL: daemon.json enables live-restore; resolve before installation.')
    print('PASS: ARM64 daemon, NVMe Docker storage and storage-shutdown compatibility')
