#!/usr/bin/env bash
set -Eeuo pipefail
source /srv/docker/scripts/common.sh
root_required
failed=0
if verify_storage --only root; then echo 'PASS: NVMe root identity, writable filesystem and free space'; else echo 'FAIL: NVMe root storage'; failed=1; fi
python3 /srv/docker/scripts/storage-status.py --quiet || true
if systemctl is-active --quiet docker; then echo 'PASS: Docker daemon'; else echo 'FAIL: Docker'; failed=1; fi
if systemctl is-active --quiet pi-storage-watch.timer; then echo 'PASS: storage timer'; else echo 'FAIL: storage timer'; failed=1; fi
if python3 /srv/docker/scripts/manage.py verify; then echo 'PASS: enabled container and HTTP checks'; else echo 'FAIL: one or more enabled applications; see /srv/docker/logs/verify-report.txt'; failed=1; fi
ip=$(sed -n 's/^BIND_IP=//p' /srv/docker/server.env)
if dig +time=3 +tries=1 "@$ip" example.com A | grep -q 'status: NOERROR'; then echo 'PASS: Pi-hole DNS'; else echo 'FAIL: Pi-hole DNS query'; failed=1; fi
if getent hosts registry-1.docker.io >/dev/null; then echo 'PASS: host DNS independent connectivity'; else echo 'FAIL: host DNS'; failed=1; fi
for path in /mnt/hdd/Nextcloud /mnt/hdd/Paperless /mnt/media/Videos /mnt/media/Music; do
    if findmnt --mountpoint "${path%/*}" >/dev/null 2>&1 && [[ -d $path ]]; then
        echo "PASS: verified data directory exists: $path"
    else
        echo "WARNING: data drive or directory unavailable: $path (dependent app remains stopped)"
    fi
done
if [[ -f /srv/docker/configs/reboot-files.sha256 ]]; then
    if sha256sum -c /srv/docker/configs/reboot-files.sha256; then echo 'PASS: selected unchanged file checksums'; else echo 'FAIL: checksum change; inspect whether app legitimately updated file'; failed=1; fi
else echo 'WARNING: data presence does not prove integrity; record representative unchanged file checksums before reboot (README).'; fi
if [[ -f /srv/docker/backups/last-success ]]; then echo 'PASS: backup history exists'; else echo 'WARNING: no completed backup recorded'; fi
if [[ $(timedatectl show -p NTPSynchronized --value) == yes ]]; then echo 'PASS: NTP synchronized'; else echo 'WARNING: NTP not synchronized'; fi
free -h
if [[ -r /sys/class/thermal/thermal_zone0/temp ]]; then awk '{printf "CPU temperature: %.1f C\n",$1/1000}' /sys/class/thermal/thermal_zone0/temp; fi
echo 'Manually open one Nextcloud file/Paperless document and play one track/video after reboot.'
exit "$failed"
