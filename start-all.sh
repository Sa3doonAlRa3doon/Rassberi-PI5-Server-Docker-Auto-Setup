#!/usr/bin/env bash
set -Eeuo pipefail
source /srv/docker/scripts/common.sh
root_required
lock_server
verify_storage --only root
exec python3 /srv/docker/scripts/manage.py start "$@"
