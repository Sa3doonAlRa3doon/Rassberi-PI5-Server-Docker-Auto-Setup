#!/usr/bin/env bash
set -Eeuo pipefail
# Terminal display suitable for a later small HDMI/DSI console; no desktop installed.
exec watch -n 15 --color 'sudo /srv/docker/status.sh'
