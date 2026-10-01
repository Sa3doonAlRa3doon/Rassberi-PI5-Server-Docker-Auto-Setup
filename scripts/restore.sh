#!/usr/bin/env bash
# Compatibility entry point for safe, layout-aware staging recovery.
#
# It intentionally does not extract old nvme.tar.gz/bulk.tar.gz archives into
# production paths. Those archives were coupled to a fixed mount layout and
# cannot be made safe for an arbitrary custom storage plan by a shell wrapper.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PORTABLE="$SCRIPT_DIR/portable-backup.py"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
usage() {
  cat <<'EOF'
Usage:
  restore.sh verify --snapshot SNAPSHOT_PATH [--json]
  restore.sh restore-plan --snapshot SNAPSHOT_PATH --destination NEW_STAGING_PATH [--json]
  sudo restore.sh restore --snapshot SNAPSHOT_PATH --destination NEW_STAGING_PATH \
    --destination-uuid RECOVERY_FILESYSTEM_UUID [--json]

A single SNAPSHOT_PATH is accepted as a compatibility shortcut for
"verify --snapshot SNAPSHOT_PATH". Recovery is always staged into a new,
empty directory; active application paths are never overwritten.

Legacy nvme.tar.gz/bulk.tar.gz archives are deliberately refused. Their old
restore procedure assumed fixed production mount paths and UUIDs. Preserve
those archives and consult the release that created them; create new portable
snapshots for layout-independent recovery.
EOF
}

[[ -r "$PORTABLE" ]] || die "Missing portable backup program: $PORTABLE"
command -v python3 >/dev/null || die 'Missing required command: python3'

case "${1:-}" in
  -h|--help|'')
    usage
    [[ $# -gt 0 ]] && exit 0
    exit 2
    ;;
esac

for argument in "$@"; do
  case "$argument" in
    --confirm-restore|--restore-bulk)
      die "Legacy restore flags are unsupported. Use the portable restore commands shown by --help."
      ;;
  esac
done

case "$1" in
  verify|restore-plan|restore)
    exec python3 "$PORTABLE" "$@"
    ;;
esac

# Old `restore.sh BACKUP_DIRECTORY` was a read-only verification by default.
# Keep the safe part of that interface for portable snapshots only.
if [[ $# -eq 1 ]]; then
  snapshot=$1
  if [[ -d "$snapshot" && ( -e "$snapshot/nvme.tar.gz" || -e "$snapshot/bulk.tar.gz" || -e "$snapshot/database-map.tsv" || -e "$snapshot/backup-info.txt" ) ]]; then
    die "Legacy tar archive refused: it has no portable layout metadata and would require fixed storage paths."
  fi
  exec python3 "$PORTABLE" verify --snapshot "$snapshot"
fi

usage
exit 2
