#!/usr/bin/env bash
set -Eeuo pipefail
exec python3 /srv/docker/scripts/setup-tailscale-homepage.py "$@"
