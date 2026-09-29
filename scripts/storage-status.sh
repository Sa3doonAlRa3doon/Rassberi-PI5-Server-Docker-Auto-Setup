#!/usr/bin/env bash
set -Eeuo pipefail
exec python3 /srv/docker/scripts/storage-status.py "$@"
