#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
exec python3 /srv/docker/scripts/portable-backup.py "$@"
