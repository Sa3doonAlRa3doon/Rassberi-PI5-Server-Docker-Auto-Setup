#!/usr/bin/env python3
"""Sequential service operations, collision checks, ARM64 checks, and honest reports."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = Path('/srv/docker')
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(BASE / 'scripts'))
import app_selection

def now(): return datetime.now(timezone.utc).isoformat()

def compose(app, *args, **kwargs):
    command=['docker','compose','--project-name','pi-'+app,'--project-directory',str(BASE/'compose'/app),
             '--env-file',str(BASE/'compose'/app/'.env'),'-f',str(BASE/'compose'/app/'compose.yml'),*args]
    return subprocess.run(command, **kwargs)

def config(app):
    p=compose(app,'config','--format','json',capture_output=True,text=True)
    if p.returncode: raise RuntimeError('Compose validation failed: '+p.stderr.strip())
    return json.loads(p.stdout)

def containers(app):
    ids=subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project=pi-'+app],text=True).split()
    return json.loads(subprocess.check_output(['docker','inspect',*ids],text=True)) if ids else []

def storage(app=None, write_test=False):
    command = ['python3', str(BASE/'scripts/storage_guard.py'),
               '--config', str(BASE/'configs/storage.json'),
               '--manifest', str(BASE/'manifest.json')]
    if app:
        command += ['--app', app, '--directories']
    else:
        command += ['--only', 'root']
    if write_test:
        command.append('--write-test')
    subprocess.run(command, check=True)


def selected_apps(manifest, installed, enabled, action, requested=(), all_apps=False):
    """Return only applications that the requested operation may touch.

    Installation prepares every selected app, including on-demand ones. It
    must never walk every supported manifest entry: a custom install has no
    private environment or reviewed storage for apps that were not selected.
    """
    if requested:
        names = set(requested)
    elif action == 'install':
        names = set(installed)
    elif all_apps:
        names = {app['name'] for app in manifest}
    else:
        names = set(enabled)
    return [app for app in manifest if app['name'] in names]

def verify_ports(app, cfg):
    manifest_path = BASE / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else []
    entry = next((a for a in manifest if a['name'] == app), {})
    live = containers(app)
    if any(s.get('network_mode') == 'host' for s in cfg['services'].values()) and not any(c['State']['Status'] == 'running' for c in live):
        for port in entry.get('ports', []):
            if port.get('host_network') or entry.get('host_network') or any(s.get('network_mode') == 'host' for s in cfg['services'].values()):
                proto = port.get('protocol', 'tcp')
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if proto == 'udp' else socket.SOCK_STREAM)
                try:
                    sock.bind(('0.0.0.0', int(port['host'])))
                except OSError as exc:
                    raise RuntimeError(f'Host-network port unavailable: {port["host"]}/{proto}: {exc}') from exc
                finally:
                    sock.close()
    # Existing containers from this same Compose project may have been created
    # with a wildcard host bind while the current package uses BIND_IP (or the
    # reverse).  The published port is still owned by this project, so do not
    # report its own container as a foreign collision.  Ports belonging to a
    # different project are still caught by the bind probe below.
    owned={(int(p['HostPort']),key.split('/')[1]) for c in containers(app)
           for key, ps in (c.get('NetworkSettings',{}).get('Ports') or {}).items() for p in (ps or [])}
    for svc in cfg['services'].values():
        for port in svc.get('ports',[]):
            host,number,proto=port.get('host_ip','0.0.0.0'),int(port['published']),port.get('protocol','tcp')
            if (number,proto) in owned: continue
            sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM if proto=='udp' else socket.SOCK_STREAM)
            try: sock.bind((host,number))
            except OSError as exc: raise RuntimeError(f'Host port conflict/unavailable: {host}:{number}/{proto}: {exc}') from exc
            finally: sock.close()

def verify_arch(app, cfg):
    for service in cfg['services'].values():
        image=service['image']
        data=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0]
        if data.get('Architecture')!='arm64' or data.get('Os')!='linux':
            raise RuntimeError('Image is not native linux/arm64: '+image)

def verify_memory(app, cfg):
    info=json.loads(subprocess.check_output(['docker','info','--format','{{json .}}'],text=True))
    total=int(info['MemTotal'])
    budget=total-2*1024**3
    ids=subprocess.check_output(['docker','ps','-q'],text=True).split()
    live=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True)) if ids else []
    other=sum(int(c['HostConfig'].get('Memory') or 0) for c in live if c['Config'].get('Labels',{}).get('com.docker.compose.project')!='pi-'+app)
    requested=sum(int(s.get('mem_limit',0)) for s in cfg['services'].values())
    if other+requested>budget:
        raise RuntimeError(f'RAM budget exceeded: capped workloads would use {(other+requested)/1024**3:.2f} GiB, leaving less than 2 GiB for the OS. Stop unused apps first using stop-all.sh APP; then retry.')

def check_live(app, cfg, attempts=30):
    wanted={k for k,v in cfg['services'].items() if not v.get('profiles')}
    for attempt in range(attempts):
        items=containers(app)
        seen={c['Config']['Labels'].get('com.docker.compose.service'):c for c in items}
        bad=[]
        for name in wanted:
            c=seen.get(name)
            if not c: bad.append(name+':missing'); continue
            state=c['State']; health=state.get('Health',{}).get('Status')
            if state['Status']!='running' or (health and health!='healthy'):
                bad.append(name+':'+state['Status']+'/'+str(health))
        if not bad: break
        if attempt+1<attempts: time.sleep(4)
    if bad: raise RuntimeError('; '.join(bad))
    warnings=[]
    for name in wanted:
        if not seen[name]['State'].get('Health'):
            warnings.append(name+': no container healthcheck; running state and HTTP checked separately')
    # HTTP reachability complements, but does not replace, application health checks.
    for svc in cfg['services'].values():
        for p in svc.get('ports',[]):
            if int(p['published']) in {53,2222,22000,21027}: continue
            proto='https' if int(p['published'])==9443 else 'http'
            url=f"{proto}://{p.get('host_ip','127.0.0.1')}:{p['published']}/"
            if proto=='https':
                warnings.append(url+': self-signed TLS; verify browser certificate and finish first login')
                continue
            okay=False
            for retry in range(min(attempts,12)):
                try:
                    with urllib.request.urlopen(url,timeout=5) as r: okay=r.status<500
                except urllib.error.HTTPError as exc:
                    okay=exc.code in {400,401,403,404,405,429}
                except (OSError,urllib.error.URLError): pass
                if okay: break
                if retry+1<min(attempts,12): time.sleep(5)
            if not okay: raise RuntimeError('HTTP endpoint did not respond acceptably: '+url)
    return warnings

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['list','install','start','stop','update','verify'])
    p.add_argument('apps',nargs='*')
    p.add_argument('--report-dir',default=str(BASE/'logs'))
    p.add_argument('--all',action='store_true')
    args=p.parse_args()
    manifest=json.loads((BASE/'manifest.json').read_text())
    manifest.sort(key=lambda x:x.get('order',50))
    installed=set(app_selection.installed_names(BASE, manifest))
    enabled=set(app_selection.startup_names(BASE, manifest)) & installed
    unknown=set(args.apps)-{a['name'] for a in manifest}
    if unknown: raise RuntimeError('Unknown applications: '+','.join(sorted(unknown)))
    not_installed=set(args.apps)-installed
    if not_installed and args.action in {'start', 'install', 'update', 'verify'}:
        raise RuntimeError('Application is not selected for installation: '+','.join(sorted(not_installed))+
                           '. Choose it in the settings page and save the application selection first.')
    if args.action=='list':
        pool = set(a['name'] for a in manifest) if args.all else installed
        print('\n'.join(a['name'] for a in manifest if a['name'] in pool)); return 0
    if os.geteuid()!=0: raise RuntimeError('Run with sudo.')
    subprocess.run(['docker','info'],stdout=subprocess.DEVNULL,check=True)
    if args.action!='stop': storage()
    selected=selected_apps(manifest, installed, enabled, args.action, args.apps, args.all)
    if args.action in {'start', 'install', 'update'}:
        names = {a['name'] for a in selected}
        changed = True
        while changed:
            before = set(names)
            for app in manifest:
                if app['name'] in names:
                    names.update(app.get('requires', []))
            changed = names != before
        if names - {a['name'] for a in manifest}:
            raise RuntimeError('Unknown cross-project dependency')
        selected = [a for a in manifest if a['name'] in names]
    if args.action=='stop': selected.reverse()
    configs={}
    declared={}
    for app in selected:
        if app.get('blocked_reason'): continue
        try: cfg=config(app['name'])
        except Exception:
            if app in selected and args.action in {'install','start','update'}: continue
            else: continue
        configs[app['name']]=cfg
        for service_name,service in cfg['services'].items():
            for port in service.get('ports',[]):
                key=(port.get('host_ip','0.0.0.0'),int(port['published']),port.get('protocol','tcp'))
                if key in declared:
                    raise RuntimeError(f'Duplicate host port {key}: {declared[key]} and {app["name"]}')
                declared[key]=app['name']+'/'+service_name
    reportdir=Path(args.report_dir); reportdir.mkdir(parents=True,exist_ok=True,mode=0o700)
    rows=[]
    for app in selected:
        name=app['name']; row={'application':name,'start':now(),'compose':str(BASE/'compose'/name/'compose.yml'),
          'ports':app.get('ports',[]),'persistent_storage':app.get('directories',[]),'database':app.get('database'),
          'images':app.get('images',[]),'architecture':'not yet verified','result':'ERROR','warnings':[]}
        logpath=reportdir/(name+'-'+args.action+'.log'); row['log']=str(logpath)
        print(f'[{args.action}] {name}',flush=True)
        try:
            if app.get('blocked_reason'):
                raise RuntimeError(app['blocked_reason'])
            values = {}
            envfile = BASE / 'compose' / name / '.env'
            if envfile.exists():
                values = dict(line.split('=', 1) for line in envfile.read_text().splitlines() if '=' in line and not line.lstrip().startswith('#'))
            missing = [key for key in app.get('required_before_start', []) if not values.get(key, '').strip()]
            if missing and args.action != 'stop':
                if args.action == 'install':
                    for entry in app.get('images', []):
                        subprocess.run(['docker', 'pull', '--platform', 'linux/arm64', entry['image']], check=True, stdout=subprocess.DEVNULL)
                    row['result'] = 'SKIPPED'
                    row['warnings'] = ['Images installed; configuration required before start: ' + ', '.join(missing)]
                    row['end'] = now(); rows.append(row)
                    continue
                raise RuntimeError('Configure before start: ' + ', '.join(missing))
            holdsfile = BASE / 'configs/storage-review-required.json'
            if args.action != 'stop' and holdsfile.exists() and name in json.loads(holdsfile.read_text()):
                raise RuntimeError('Storage review hold remains for ' + name + '; verify recovered files before clearing it')
            if args.action != 'stop':
                # Drive loss is scoped to the application that needs it. Other apps continue.
                try:
                    storage(app=name)
                except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
                    row['result'] = 'ERROR'
                    row['warnings'] = ['Storage dependency unavailable; application left stopped: ' + str(exc)]
                    row['error'] = str(exc)
                    row['end'] = now()
                    rows.append(row)
                    print('SKIPPED: ' + name + ': storage dependency unavailable', flush=True)
                    continue
            cfg=configs.get(name) or config(name)
            with logpath.open('a',encoding='utf-8') as log:
                log.write('\nOperation '+args.action+' '+now()+'\n'); log.flush()
                if args.action=='stop':
                    compose(name,'stop','--timeout','90',stdout=log,stderr=log,check=True)
                elif args.action=='verify':
                    row['warnings']=check_live(name,cfg,attempts=1)
                else:
                    previously_running={c['Config']['Labels'].get('com.docker.compose.service') for c in containers(name) if c['State']['Status']=='running'} if args.action=='update' else None
                    if args.action in {'install','update'}:
                        if any('build' in s for s in cfg['services'].values()):
                            compose(name,'build','--pull',stdout=log,stderr=log,check=True)
                        compose(name,'pull','--ignore-buildable','--policy','always' if args.action=='update' else 'missing',stdout=log,stderr=log,check=True)
                    verify_arch(name,cfg); row['architecture']='linux/arm64 verified locally'
                    prepare=BASE/'compose'/name/'prepare.sh'
                    if prepare.exists():
                        subprocess.run(['bash',str(prepare)],cwd=prepare.parent,env={**os.environ,'COMPOSE_PROJECT_NAME':'pi-'+name},stdout=log,stderr=log,check=True)
                        cfg = config(name)
                    if (args.action=='install' and name not in enabled) or (args.action=='update' and not previously_running):
                        row['result']='SKIPPED'; row['warnings']=['Prepared and images verified; on demand. Start with sudo /srv/docker/start-all.sh '+name]
                    else:
                        storage(app=name)
                        verify_ports(name,cfg)
                        active_cfg={**cfg,'services':{k:v for k,v in cfg['services'].items() if previously_running is None or k in previously_running}}
                        verify_memory(name,active_cfg)
                        up=['up','-d','--wait','--wait-timeout','1200']
                        if previously_running is not None: up+=['--no-deps',*sorted(previously_running)]
                        compose(name,*up,stdout=log,stderr=log,check=True)
                        row['warnings']=check_live(name,active_cfg)
                        post = BASE / 'compose' / name / 'post-start.sh'
                        if post.is_file():
                            subprocess.run(['bash', str(post)], cwd=post.parent, stdout=log, stderr=log, check=True)
                if row['result']!='SKIPPED': row['result']='SUCCESS'
                row['containers']=[{'name':c['Name'],'status':c['State']['Status'],'health':c['State'].get('Health',{}).get('Status','not configured')} for c in containers(name)]
                if args.action=='install' and app.get('setup'): row['warnings'].append('First-run setup: '+app['setup'])
        except Exception as exc:
            row['error']=str(exc)
            with logpath.open('a') as log:
                log.write('\nERROR: '+str(exc)+'\n')
                compose(name,'ps','--all',stdout=log,stderr=log)
                compose(name,'logs','--no-color','--tail','60',stdout=log,stderr=log)
            print('ERROR: '+name+': '+str(exc)+'; log '+str(logpath),flush=True)
        row['end']=now(); rows.append(row)
    successes=sum(r['result']=='SUCCESS' for r in rows)
    failed=sum(r['result']=='ERROR' for r in rows)
    skipped=sum(r['result']=='SKIPPED' for r in rows)
    warnings=sum(bool(r['warnings']) for r in rows)
    reportname='installation-report' if args.action=='install' else args.action+'-report'
    (reportdir/(reportname+'.json')).write_text(json.dumps(rows,indent=2)+'\n')
    lines=[]
    for r in rows:
        lines.extend([r['result']+': '+r['application'],'Compose: '+r['compose'],'Start: '+r['start'],'End: '+r['end'],
          'Architecture: '+r['architecture'],'Log: '+r['log'],'Error: '+r.get('error','none')])
        lines.extend('WARNING: '+w for w in r['warnings'])
        lines.append('Details: '+json.dumps({k:r.get(k) for k in ['images','ports','persistent_storage','database','containers']}))
    banner='DONE - BUT RAN INTO ERRORS' if failed else 'DONE - REVIEW WARNINGS / ON-DEMAND SERVICES' if warnings or skipped else 'DONE\nALL SERVICES INSTALLED SUCCESSFULLY'
    lines += ['='*45,banner,f'SUCCESSFUL SERVICES: {successes}; FAILED SERVICES: {failed}; ON DEMAND: {skipped}; WARNINGS: {warnings}','='*45]
    if failed:
        lines.append('FAILED SERVICE DETAILS:')
        lines.extend(f"ERROR: {row['application']}: {row.get('error', 'unknown failure')}"
                     for row in rows if row['result'] == 'ERROR')
    (reportdir/(reportname+'.txt')).write_text('\n'.join(lines)+'\n')
    (reportdir/(reportname+'.log')).write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines[-min(12, len(lines)):]),flush=True)
    return 2 if failed else 0

if __name__=='__main__':
    try: sys.exit(main())
    except (RuntimeError,subprocess.SubprocessError,OSError,ValueError) as exc:
        print('CRITICAL: '+str(exc),file=sys.stderr); sys.exit(1)
