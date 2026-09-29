#!/usr/bin/env bash
set -Eeuo pipefail
exec /srv/docker/scripts/backup.sh "$@"
