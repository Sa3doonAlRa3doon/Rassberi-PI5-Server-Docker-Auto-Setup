#!/usr/bin/env bash
set -Eeuo pipefail
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ $EUID -ne 0 ]]; then exec sudo python3 "$SOURCE/scripts/upgrade-package.py" "$@"; fi
exec python3 "$SOURCE/scripts/upgrade-package.py" "$@"
