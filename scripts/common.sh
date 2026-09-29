#!/usr/bin/env bash
set -Eeuo pipefail
BASE=/srv/docker
root_required() { [[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }; }
verify_storage() { python3 "$BASE/scripts/storage_guard.py" "$@"; }
lock_server() { exec 9>/run/lock/pi-server.lock; flock -n 9 || { echo 'Another installation/backup/update is active.' >&2; exit 1; }; }
compose() { local app=$1; shift; docker compose --project-name "pi-$app" --project-directory "$BASE/compose/$app" --env-file "$BASE/compose/$app/.env" -f "$BASE/compose/$app/compose.yml" "$@"; }
app_names() { python3 "$BASE/scripts/manage.py" list "$@"; }
