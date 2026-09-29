#!/usr/bin/env bash
set -Eeuo pipefail
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ $EUID -ne 0 ]]; then exec sudo bash "$SOURCE/apply-storage-update.sh" "$@"; fi
exec python3 "$SOURCE/scripts/apply-storage-update.py" "$@"
