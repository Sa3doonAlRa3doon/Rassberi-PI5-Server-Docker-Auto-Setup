#!/usr/bin/env bash
# Fresh-target recovery only. Never deletes or overwrites existing application data.
set -Eeuo pipefail
umask 077
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
usage() { echo "Usage: sudo $0 BACKUP_DIRECTORY [--confirm-restore] [--restore-bulk]"; }
[[ $EUID == 0 ]] || die 'Run with sudo.'
[[ $# -ge 1 ]] || { usage; exit 2; }
SOURCE=$(realpath -e -- "$1"); shift
CONFIRM=0; BULK=0
for argument in "$@"; do
  case $argument in
    --confirm-restore) CONFIRM=1;;
    --restore-bulk) BULK=1;;
    *) usage; exit 2;;
  esac
done
for tool in python3 sha256sum docker tar findmnt mountpoint flock; do command -v "$tool" >/dev/null || die "Missing command: $tool"; done
[[ -f $SOURCE/COMPLETE && -s $SOURCE/SHA256SUMS && -s $SOURCE/nvme.tar.gz ]] || die 'Not a complete backup directory.'
install -d -m 0755 /run/lock
exec 9>/run/lock/pi-server.lock
flock -n 9 || die 'Another installer, update, backup or restore is running.'
# Validate archive paths and links before root extraction. A checksum is not proof
# of authenticity: use only your own trusted backups and protect their contents.
python3 - "$SOURCE" <<'PY'
import pathlib,posixpath,sys,tarfile
source=pathlib.Path(sys.argv[1])
for line in (source/'SHA256SUMS').read_text().splitlines():
    if len(line)<67 or line[64:66] not in ('  ',' *'): raise SystemExit('Invalid checksum entry')
    name=line[66:]
    p=pathlib.PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name: raise SystemExit('Unsafe checksum path')
    resolved=(source/name).resolve()
    if not resolved.is_relative_to(source): raise SystemExit('Checksum path escapes backup')
for filename in ('nvme.tar.gz','bulk.tar.gz'):
    if not (source/filename).exists(): continue
    with tarfile.open(source/filename,'r:gz') as archive:
        links=set()
        for entry in archive:
            p=pathlib.PurePosixPath(entry.name)
            if p.is_absolute() or '..' in p.parts: raise SystemExit('Unsafe archive path')
            if entry.isdev() or entry.isfifo(): raise SystemExit('Device/FIFO archive entries are unsupported')
            if filename=='nvme.tar.gz' and p.parts and p.parts[0] in ('databases','backups','restore'):
                raise SystemExit('NVMe archive contains forbidden data tree')
            if filename=='bulk.tar.gz' and not any(str(p)==base or str(p).startswith(base+'/') for base in (
                'mnt/hdd/Nextcloud','mnt/hdd/Paperless','mnt/hdd/Books','mnt/hdd/Kiwix',
                'mnt/hdd/Shared','mnt/hdd/Uploads','mnt/media/Music','mnt/media/Videos')):
                raise SystemExit('Unexpected bulk-data path')
            if entry.issym() or entry.islnk():
                target=posixpath.normpath(posixpath.join(str(p.parent) if entry.issym() else '',entry.linkname))
                if target.startswith('/') or target=='..' or target.startswith('../'):
                    raise SystemExit('Archive contains a link outside its extraction root; manual review required')
                links.add(str(p))
        for entry in archive.getmembers():
            if any(str(parent) in links for parent in pathlib.PurePosixPath(entry.name).parents):
                raise SystemExit('Archive entry traverses another archived link')
PY
(cd "$SOURCE" && sha256sum --check --strict SHA256SUMS)
echo 'PASS: checksums and archive paths verified.'
if (( CONFIRM == 0 )); then
  echo 'Verification only. --confirm-restore enables fresh-target recovery and starts database containers temporarily.'
  exit 0
fi
if (( BULK == 1 )); then [[ -s $SOURCE/bulk.tar.gz ]] || die 'This backup excludes HDD/media data; no bulk restore is available.'; fi
for spec in '/mnt/hdd:a8293b36-2c0e-4852-84fd-92ac7503f4db' '/mnt/media:17e44bc7-f360-45c4-878b-a7fe7aa45f6e'; do
  path=${spec%%:*}; uuid=${spec#*:}
  mountpoint -q "$path" || die "Mount the prepared physical filesystem first: $path"
  [[ $(findmnt -nro UUID -M "$path") == "$uuid" ]] || die "Wrong filesystem UUID: $path"
done
[[ $(findmnt -nro SOURCE -M /) == /dev/nvme0n1p2 ]] || die 'Root must be the expected /dev/nvme0n1p2 NVMe partition.'
[[ ! -L /srv && ! -L /srv/docker ]] || die 'Symlinked /srv or /srv/docker is unsafe.'
install -d -m 0755 /srv/docker
[[ $(stat -c %d /srv/docker) == "$(stat -c %d /)" ]] || die '/srv/docker is not on the root NVMe filesystem.'
# Existing backups can stay; every other server tree must be moved aside manually.
unexpected=$(find /srv/docker -mindepth 1 -maxdepth 1 ! -name backups -print -quit)
[[ -z $unexpected ]] || die "Existing server state detected ($unexpected). Stop the old stacks and preserve/move the entire old /srv/docker before recovery."
if (( BULK == 1 )); then
  for path in /mnt/hdd/{Nextcloud,Paperless,Books,Kiwix,Shared,Uploads} /mnt/media/{Music,Videos}; do
    [[ ! -L $path ]] || die "Bulk destination is a symlink: $path"
    [[ ! -e $path || -d $path ]] || die "Bulk destination is not a directory: $path"
    [[ ! -d $path || -z $(find "$path" -mindepth 1 -print -quit) ]] || die "Bulk destination contains existing files: $path"
  done
fi
# All existing project containers, even stopped ones, must be removed before a
# disaster restore so old bind paths, credentials and metadata cannot be reused.
existing=$(docker ps -a --format '{{.ID}} {{.Label "com.docker.compose.project"}}' --filter label=com.docker.compose.project | python3 -c 'import sys; print("\n".join(n.strip() for n in sys.stdin if len(n.split())==2 and n.split()[1].startswith("pi-")))')
[[ -z $existing ]] || die 'Old pi-* containers exist. Run each old stack compose down (never -v), then retry.'
python3 - "$SOURCE" "$BULK" <<'PY'
import os,pathlib,sys,tarfile
source=pathlib.Path(sys.argv[1]); sizes={'/srv/docker':0,'/mnt/hdd':0,'/mnt/media':0}
with tarfile.open(source/'nvme.tar.gz','r:gz') as archive:
    sizes['/srv/docker']=sum(e.size for e in archive if e.isfile())
sizes['/srv/docker']+=sum(p.stat().st_size*5 for p in (source/'databases').glob('*'))
if sys.argv[2]=='1':
    with tarfile.open(source/'bulk.tar.gz','r:gz') as archive:
        for e in archive:
            if e.isfile(): sizes['/mnt/hdd' if e.name.startswith('mnt/hdd/') else '/mnt/media']+=e.size
for mount,size in sizes.items():
    v=os.statvfs(mount)
    if v.f_bavail*v.f_frsize<size+5*1024**3: raise SystemExit(f'Insufficient free space at {mount}; need data plus 5 GiB reserve')
PY
tar --numeric-owner --same-owner --acls --xattrs --keep-old-files -xzf "$SOURCE/nvme.tar.gz" -C /srv/docker
if (( BULK == 1 )); then
  # Empty top-level directories may already exist; their files are guaranteed absent.
  tar --numeric-owner --same-owner --acls --xattrs --keep-old-files -xzf "$SOURCE/bulk.tar.gz" -C /
fi
[[ -f /srv/docker/scripts/common.sh ]] || die 'Backup is missing runtime scripts.'
source /srv/docker/scripts/common.sh
verify_storage
install -d -m 0750 /srv/docker/databases /srv/docker/backups /srv/docker/logs
python3 - /srv/docker/manifest.json <<'PY'
import json,os,pathlib,sys
data=json.load(open(sys.argv[1]))
if isinstance(data,dict): data=data['applications']
for app in data:
    for d in app.get('directories',[]):
        path=pathlib.Path(d['path'])
        if not str(path).startswith('/srv/docker/databases/'): continue
        path.mkdir(parents=True,exist_ok=True)
        os.chown(path,int(d.get('uid',0)),int(d.get('gid',0)))
        os.chmod(path,int(str(d.get('mode','0700')),8))
PY
declare -a DB_CONTAINERS=()
cleanup() {
  local result=$?
  trap - EXIT INT TERM
  for id in "${DB_CONTAINERS[@]}"; do docker stop -t 120 "$id" >/dev/null || result=1; done
  if (( result != 0 )); then echo 'FAILED: restored state was preserved for investigation. Applications remain stopped; do not start them until recovery is complete.' >&2; fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
while IFS=$'\t' read -r app kind service dbname dbuser; do
  dump="$SOURCE/databases/$app.dump"
  [[ $kind != mariadb ]] || dump="$SOURCE/databases/$app.sql"
  if [[ ! -s $dump ]]; then
    echo "WARNING: no saved database for $app; leave it disabled until initialized or recovered."
    continue
  fi
  compose "$app" up -d --no-deps "$service"
  id=$(compose "$app" ps -a -q "$service")
  [[ -n $id && $id != *$'\n'* ]] || die "Expected one database container: $app"
  DB_CONTAINERS+=("$id")
  ready=0
  for ((attempt=0; attempt<120; attempt++)); do
    if [[ $kind == postgres ]]; then
      if docker exec "$id" pg_isready -U "$dbuser" -d "$dbname" >/dev/null 2>&1; then ready=1; break; fi
    elif [[ $kind == mariadb ]]; then
      if docker exec "$id" sh -c 'MYSQL_PWD="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}" exec mariadb-admin ping -uroot --silent' >/dev/null 2>&1; then ready=1; break; fi
    else die "Unsupported database engine: $kind"; fi
    sleep 2
  done
  (( ready == 1 )) || die "Database readiness timeout: $app"
  echo "Restoring logical database: $app"
  if [[ $kind == postgres ]]; then
    docker exec -i "$id" pg_restore -U "$dbuser" -d "$dbname" --no-owner --no-acl --exit-on-error <"$dump"
  else
    docker exec -i -e RESTORE_DATABASE="$dbname" "$id" sh -c 'MYSQL_PWD="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}" exec mariadb -uroot "$RESTORE_DATABASE"' <"$dump"
  fi
  docker stop -t 120 "$id" >/dev/null
  DB_CONTAINERS=()
done <"$SOURCE/database-map.tsv"
echo 'PASS: fresh-target restore completed. All application stacks are stopped.'
echo 'Read /srv/docker/docs/RECOVERY.md, restore the host mount guard/configuration, then run the guarded start-all.sh and verify-after-reboot.sh.'
(( BULK == 1 )) || echo 'WARNING: HDD and microSD contents were not restored. Supply matching user data before starting Nextcloud/Paperless and other file services.'
