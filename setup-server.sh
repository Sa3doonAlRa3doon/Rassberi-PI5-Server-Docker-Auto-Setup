#!/usr/bin/env bash
set -Eeuo pipefail
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ $EUID -ne 0 ]]; then exec sudo bash "$SOURCE/setup-server.sh" "$@"; fi
command -v python3 >/dev/null
python3 "$SOURCE/scripts/platform_check.py"
for tool in openssl lsblk findmnt; do command -v "$tool" >/dev/null; done
exec python3 "$SOURCE/scripts/settings_server.py" --setup "$@"
