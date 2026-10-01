#!/usr/bin/env bash
set -Eeuo pipefail
source /srv/docker/scripts/common.sh
root_required
verify_storage --only root
echo 'Creating a consistent backup before the controlled update.'
if ! /srv/docker/scripts/backup.sh --plan --json >/dev/null; then
  echo 'CRITICAL: update blocked because no ready portable backup disk is configured. Configure and verify it in Settings or portable-backup.json first.' >&2
  exit 2
fi
/srv/docker/scripts/backup.sh
lock_server
echo 'Pulling the explicit pinned images in each current Compose file. No major-version substitution.'
exec python3 /srv/docker/scripts/manage.py update "$@"
