#!/usr/bin/env bash
set -Eeuo pipefail
source /srv/docker/scripts/common.sh
root_required
echo '=== STORAGE ==='
python3 /srv/docker/scripts/storage-status.py || true
echo '=== CONTAINERS: running / restarting / healthy / unhealthy / stopped ==='
docker ps -a --filter label=com.docker.compose.project --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' || true
echo '=== HOST ==='
free -h
uptime
hostname -I
if [[ -r /sys/class/thermal/thermal_zone0/temp ]]; then awk '{printf "CPU temperature: %.1f C\n",$1/1000}' /sys/class/thermal/thermal_zone0/temp; fi
if command -v tailscale >/dev/null; then tailscale status || true; else echo 'Tailscale: not installed on host'; fi
echo '=== BACKUP ==='
if [[ -f /srv/docker/backups/last-success ]]; then cat /srv/docker/backups/last-success; else echo 'WARNING: no successful backup recorded'; fi
echo '=== SMART ==='
systemctl is-active smartmontools.service || true
systemctl is-active pi-storage-metrics.timer || true
echo 'Full disk health: sudo /srv/docker/scripts/disk-health.sh'
