#!/usr/bin/env bash
# Compatibility entry point for the layout-aware portable backup workflow.
#
# Earlier package releases made a tar archive that assumed the original
# NVMe/HDD/microSD mount layout. Do not recreate that archive on a custom
# installation: portable-backup.py records the selected layout and verifies
# the actual backup disk before it stops a container.
set -Eeuo pipefail
umask 077

ROOT=/srv/docker
DEFAULT_CONFIG="$ROOT/configs/portable-backup.json"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PORTABLE="$SCRIPT_DIR/portable-backup.py"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
usage() {
  cat <<'EOF'
Usage:
  sudo /srv/docker/backup.sh [--plan] [portable-backup options]

Creates a layout-aware portable snapshot using
/srv/docker/configs/portable-backup.json. Use --plan to check the configured
backup disk without stopping containers. For the full interface, use:
  sudo /srv/docker/portable-backup.sh ACTION [options]

The old root-owned backup.conf argument is no longer accepted. Configure the
backup disk in Settings or portable-backup.json so its exact mount and UUID
are checked before a maintenance backup starts.
EOF
}

[[ -r "$PORTABLE" ]] || die "Missing portable backup program: $PORTABLE"
command -v python3 >/dev/null || die 'Missing required command: python3'

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
  --plan)
    shift
    exec python3 "$PORTABLE" plan --config "$DEFAULT_CONFIG" "$@"
    ;;
esac

# The legacy interface accepted one positional shell configuration file. A
# positional first argument must never be mistaken for a portable CLI option:
# fail before the backup program takes its maintenance lock or stops
# containers. Values belonging to portable options, such as `--config PATH`,
# are forwarded unchanged.
[[ $# -eq 0 || $1 == -* ]] || die "Legacy backup.conf arguments are unsupported. Configure portable-backup.json, or use portable-backup.sh create --config PATH."

exec python3 "$PORTABLE" create --config "$DEFAULT_CONFIG" "$@"
