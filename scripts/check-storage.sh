#!/usr/bin/env bash
set -Eeuo pipefail
exec /usr/bin/python3 /srv/docker/scripts/storage_guard.py "$@"
