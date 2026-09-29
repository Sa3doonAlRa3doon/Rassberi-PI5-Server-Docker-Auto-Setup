#!/usr/bin/env bash
set -Eeuo pipefail
source /srv/docker/scripts/common.sh
root_required
lock_server
# Include on-demand applications that the user may have started.
exec python3 /srv/docker/scripts/manage.py stop --all "$@"
