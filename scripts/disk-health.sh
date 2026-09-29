#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Use sudo'; exit 1; }
python3 /srv/docker/scripts/storage-status.py
exec python3 /srv/docker/scripts/storage-health.py "$@"
