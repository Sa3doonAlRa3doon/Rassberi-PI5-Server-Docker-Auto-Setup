#!/usr/bin/env bash
set -Eeuo pipefail
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ $EUID -ne 0 ]]; then exec sudo bash "$SOURCE/select-apps.sh" "$@"; fi
BASE=/srv/docker
if [[ ! -f "$BASE/manifest.json" ]]; then BASE=$SOURCE; fi
exec python3 "$BASE/scripts/select-apps.py" --base "$BASE" "$@"
