#!/usr/bin/env bash
# Run on the Raspberry Pi, as root. A backup creates a maintenance outage.
set -Eeuo pipefail
umask 077
ROOT=/srv/docker
CONFIG="$ROOT/configs/backup.conf"
[[ $# -le 1 ]] || { echo "Usage: sudo $0 [root-owned-backup.conf]" >&2; exit 2; }
[[ $# == 0 ]] || CONFIG=$1
[[ $EUID == 0 ]] || { echo 'Run this script with sudo.' >&2; exit 1; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '%s %s\n' "$(date --iso-8601=seconds)" "$*"; }
[[ -r $ROOT/scripts/common.sh ]] || die 'Install the project before taking a backup.'
source "$ROOT/scripts/common.sh"
root_required
for tool in docker python3 tar findmnt mountpoint flock du df sha256sum realpath; do
  command -v "$tool" >/dev/null || die "Missing required command: $tool"
done
install -d -m 0755 /run/lock
exec 9>/run/lock/pi-server.lock
flock -n 9 || die 'Another installation, update, backup or restore is running.'
BACKUP_ROOT="$ROOT/backups"
BACKUP_MOUNT=''
BACKUP_INCLUDE_BULK=0
RESTIC_REPOSITORY=''
RESTIC_PASSWORD_FILE=''
if [[ -f $CONFIG ]]; then
  [[ $(stat -c %u "$CONFIG") == 0 ]] || die 'Backup configuration must be owned by root.'
  (( (8#$(stat -c %a "$CONFIG") & 8#077) == 0 )) || die 'Use chmod 600 on backup configuration.'
  # This is an explicitly trusted root-owned shell configuration, not an .env file.
  source "$CONFIG"
fi
[[ $BACKUP_INCLUDE_BULK == 0 || $BACKUP_INCLUDE_BULK == 1 ]] || die 'BACKUP_INCLUDE_BULK must be 0 or 1.'
[[ -s $ROOT/manifest.json ]] || die 'Install the project before taking a backup.'
check_storage() {
  verify_storage
}
check_storage
BACKUP_ROOT=$(realpath -m -- "$BACKUP_ROOT")
if [[ -n $BACKUP_MOUNT ]]; then
  BACKUP_MOUNT=$(realpath -e -- "$BACKUP_MOUNT")
  mountpoint -q "$BACKUP_MOUNT" || die 'External backup destination is not mounted.'
  [[ "$BACKUP_ROOT/" == "$BACKUP_MOUNT/"* ]] || die 'BACKUP_ROOT must be inside BACKUP_MOUNT.'
  [[ $(stat -c %d "$BACKUP_MOUNT") != "$(stat -c %d /)" ]] || die 'External backup must be a separate filesystem.'
  [[ $(stat -c %d "$BACKUP_MOUNT") != "$(stat -c %d /mnt/hdd)" && $(stat -c %d "$BACKUP_MOUNT") != "$(stat -c %d /mnt/media)" ]] || die 'Use another disk, not either production data drive, for external backups.'
else
  [[ $BACKUP_ROOT == "$ROOT/backups" ]] || die 'A custom BACKUP_ROOT requires BACKUP_MOUNT to prevent writing below an unmounted disk.'
fi
install -d -m 0700 "$BACKUP_ROOT" "$ROOT/backups"
if [[ -n $RESTIC_REPOSITORY ]]; then
  command -v restic >/dev/null || die 'Install restic before enabling encrypted remote backups.'
  [[ -s $RESTIC_PASSWORD_FILE ]] || die 'Missing RESTIC_PASSWORD_FILE.'
  [[ $(stat -c %u "$RESTIC_PASSWORD_FILE") == 0 ]] || die 'Restic password file must be owned by root.'
  (( (8#$(stat -c %a "$RESTIC_PASSWORD_FILE") & 8#077) == 0 )) || die 'Use chmod 600 on the restic password file.'
  export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE
  # Fail before an outage if authentication or repository initialization is missing.
  restic snapshots --last 1 >/dev/null
fi
docker info >/dev/null
docker compose version >/dev/null
declare -a APPS=() ORIGINAL=() ORIGINAL_BACKENDS=() DB_STARTED=() BULK=()
declare -A SEEN=()
app_list=$(python3 - "$ROOT/manifest.json" <<'PY'
import json,re,sys
data=json.load(open(sys.argv[1]))
if isinstance(data,dict): data=data['applications']
for app in sorted(data,key=lambda a:a.get('order',0)):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',app['name']): raise SystemExit('Invalid application name')
    print(app['name'])
PY
)
mapfile -t APPS <<<"$app_list"
[[ ${#APPS[@]} -gt 0 ]] || die 'Manifest has no applications.'
for app in "${APPS[@]}"; do
  [[ -f $ROOT/compose/$app/compose.yml ]] || continue
  # Do not call compose up: that would start services the owner deliberately stopped.
  ids=$(compose "$app" ps -a -q)
  while read -r id; do
    [[ -n $id ]] || continue
    state=$(docker inspect -f '{{.State.Status}}' "$id")
    [[ $state != paused ]] || die "Unpause $app before backing it up."
    if [[ $state == running || $state == restarting ]]; then
      [[ ${SEEN[$id]:-} ]] || ORIGINAL+=("$id")
      SEEN[$id]=1
      service=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$id")
      [[ $service != db && $service != redis ]] || ORIGINAL_BACKENDS+=("$id")
    fi
  done <<<"$ids"
done
for path in mnt/hdd/Nextcloud mnt/hdd/Paperless mnt/hdd/Books mnt/hdd/Kiwix mnt/hdd/Shared mnt/hdd/Uploads mnt/media/Music mnt/media/Videos; do
  [[ -d /$path ]] && BULK+=("$path")
done
# Estimate uncompressed inputs, twice the raw DB size, plus 1 GiB margin.
# This intentionally overestimates; no backup is allowed to consume the last 5 GiB.
estimate=1073741824
for path in appdata configs compose databases scripts; do
  [[ ! -e $ROOT/$path ]] || estimate=$((estimate + 2 * $(du -sb -- "$ROOT/$path" | cut -f1)))
done
if [[ $BACKUP_INCLUDE_BULK == 1 ]]; then
  for path in "${BULK[@]}"; do estimate=$((estimate + $(du -sb -- "/$path" | cut -f1))); done
fi
available=$(df -B1 --output=avail "$BACKUP_ROOT" | tail -n 1 | tr -d ' ')
(( available > estimate + 5368709120 )) || die "Insufficient backup space: need approximately $((estimate/1024/1024)) MiB plus 5 GiB reserve."
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PARTIAL="$BACKUP_ROOT/.incomplete-$STAMP-$$"
DEST="$BACKUP_ROOT/$STAMP"
[[ ! -e $DEST ]] || die 'A backup with this timestamp already exists.'
install -d -m 0700 "$PARTIAL/databases"
printf '%s\n' "${ORIGINAL[@]}" >"$PARTIAL/original-containers.txt"
cp -- "$ROOT/manifest.json" "$PARTIAL/manifest.json"
resumed=0
resume_original() {
  local failed=0 id ready health attempt
  for id in "${DB_STARTED[@]}"; do docker stop -t 60 "$id" >/dev/null || failed=1; done
  DB_STARTED=()
  # The mount guard is also required when recovering from an interrupted backup.
  if ! (check_storage); then
    log 'CRITICAL: storage checks failed; services stay stopped to prevent misplaced data.'
    return 1
  fi
  for id in "${ORIGINAL_BACKENDS[@]}"; do
    docker start "$id" >/dev/null || { failed=1; continue; }
    ready=0
    for ((attempt=0; attempt<120; attempt++)); do
      health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id") || break
      if [[ $health == healthy || $health == running ]]; then ready=1; break; fi
      sleep 2
    done
    (( ready == 1 )) || { log "ERROR: backend failed readiness while resuming: $id"; failed=1; }
  done
  (( failed == 0 )) || return 1
  for id in "${ORIGINAL[@]}"; do docker start "$id" >/dev/null || failed=1; done
  (( failed == 0 )) || return 1
  resumed=1
}
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if (( resumed == 0 )); then resume_original || status=1; fi
  if (( status != 0 )); then log "FAILED: no complete backup recorded; inspect $PARTIAL"; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
log "Starting maintenance backup; ${#ORIGINAL[@]} running containers will stop."
if (( ${#ORIGINAL[@]} )); then docker stop -t 120 "${ORIGINAL[@]}" >/dev/null; fi
python3 - "$ROOT/manifest.json" >"$PARTIAL/database-map.tsv" <<'PY'
import json,re,sys
data=json.load(open(sys.argv[1]))
if isinstance(data,dict): data=data['applications']
for a in data:
    db=a.get('database')
    # Only external PostgreSQL/MariaDB services get logical dumps here. Embedded
    # SQLite/application databases are captured from stopped appdata below.
    if not db or db.get('type') not in ('postgres','mariadb'): continue
    values=[a['name'],db['type'],db['service'],db['name'],db['user']]
    if any(not re.fullmatch(r'[A-Za-z0-9_.-]+',v) for v in values): raise SystemExit('Unsafe database metadata')
    print('\t'.join(values))
PY
while IFS=$'\t' read -r app kind service dbname dbuser; do
  [[ -f $ROOT/compose/$app/compose.yml ]] || continue
  id=$(compose "$app" ps -a -q "$service")
  if [[ -z $id ]]; then
    if [[ -d $ROOT/databases/$app && -n $(find "$ROOT/databases/$app" -mindepth 1 -print -quit) ]]; then
      die "$app has stored database files but no database container; recreate its db service before backing up."
    fi
    log "WARNING: $app has no initialized database container; its database is not backed up."
    printf '%s\n' "$app" >>"$PARTIAL/uninitialized-databases.txt"
    continue
  fi
  [[ $id != *$'\n'* ]] || die "Expected one database container for $app."
  DB_STARTED+=("$id")
  docker start "$id" >/dev/null
  ready=0
  for ((attempt=0; attempt<120; attempt++)); do
    if [[ $kind == postgres ]]; then
      if docker exec "$id" pg_isready -U "$dbuser" -d "$dbname" >/dev/null 2>&1; then ready=1; break; fi
    elif [[ $kind == mariadb ]]; then
      if docker exec "$id" sh -c 'MYSQL_PWD="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}" exec mariadb-admin ping -uroot --silent' >/dev/null 2>&1; then ready=1; break; fi
    else die "Unsupported database engine for $app: $kind"; fi
    sleep 2
  done
  (( ready == 1 )) || die "Database readiness timeout: $app"
  log "Dumping $app ($kind)."
  if [[ $kind == postgres ]]; then
    docker exec "$id" pg_dump -U "$dbuser" -d "$dbname" --format=custom --no-owner --no-acl >"$PARTIAL/databases/$app.dump"
    [[ -s $PARTIAL/databases/$app.dump ]] || die "Empty PostgreSQL dump: $app"
  else
    docker exec -e BACKUP_DATABASE="$dbname" "$id" sh -c 'MYSQL_PWD="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}" exec mariadb-dump -uroot --single-transaction --routines --events --triggers --hex-blob --skip-lock-tables "$BACKUP_DATABASE"' >"$PARTIAL/databases/$app.sql"
    [[ -s $PARTIAL/databases/$app.sql ]] || die "Empty MariaDB dump: $app"
  fi
  docker stop -t 120 "$id" >/dev/null
  DB_STARTED=()
done <"$PARTIAL/database-map.tsv"
check_storage
# No raw PostgreSQL or MariaDB directory is ever included in this archive.
# SQLite and application-local DBs in appdata are safe because every managed app is stopped.
python3 - "$ROOT" >"$PARTIAL/root-files.list" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1])
names=[p.name for p in root.iterdir() if p.is_file() or p.name in ('appdata','configs','compose','scripts','docs','systemd')]
sys.stdout.buffer.write(b''.join(n.encode()+b'\0' for n in sorted(names)))
PY
tar --numeric-owner --acls --xattrs --one-file-system -C "$ROOT" -czf "$PARTIAL/nvme.tar.gz" --null -T "$PARTIAL/root-files.list"
if [[ $BACKUP_INCLUDE_BULK == 1 ]]; then
  (( ${#BULK[@]} > 0 )) || die 'No bulk data directories found.'
  tar --numeric-owner --acls --xattrs --one-file-system -C / -czf "$PARTIAL/bulk.tar.gz" -- "${BULK[@]}"
fi
printf 'created_utc=%s\nbulk_included=%s\nraw_server_databases_included=0\n' "$STAMP" "$BACKUP_INCLUDE_BULK" >"$PARTIAL/backup-info.txt"
resume_original
log 'Original running containers resumed; calculating backup checksums.'
(cd "$PARTIAL" && find . -maxdepth 2 -type f ! -name SHA256SUMS ! -name COMPLETE -print0 | sort -z | xargs -0 sha256sum >SHA256SUMS)
printf 'Complete backup; validate SHA256SUMS before recovery.\n' >"$PARTIAL/COMPLETE"
mv -- "$PARTIAL" "$DEST"
if [[ -n $RESTIC_REPOSITORY ]]; then
  log 'Sending consistent archives to the configured encrypted restic repository.'
  restic backup --tag pi-server -- "$DEST"
fi
printf '%s\n%s\nbulk_included=%s\n' "$(date --iso-8601=seconds)" "$DEST" "$BACKUP_INCLUDE_BULK" >"$ROOT/backups/.last-success.$$"
mv -- "$ROOT/backups/.last-success.$$" "$ROOT/backups/last-success"
log "SUCCESS: $DEST"
[[ $BACKUP_INCLUDE_BULK == 1 ]] || log 'WARNING: HDD documents/files and microSD media are excluded. This is not a full data backup.'
[[ -n $BACKUP_MOUNT || -n $RESTIC_REPOSITORY ]] || log 'WARNING: this copy is on the source NVMe; loss of that disk also loses this backup.'
