#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ $EUID -ne 0 ]]; then exec sudo --preserve-env=BIND_IP bash "$SOURCE/install-all.sh" "$@"; fi
for tool in python3 findmnt mountpoint ip ss systemctl flock apt-get timedatectl lsblk openssl tee; do command -v "$tool" >/dev/null; done
python3 "$SOURCE/scripts/platform_check.py"
if [[ ! -f /srv/docker/server.env && ! -f "$SOURCE/configs/layout.json" ]]; then
  cat >&2 <<'MSG'
CRITICAL: this is a fresh install and no storage layout has been selected.
Choose only the apps you want and their storage in the temporary panel before any
Docker image is pulled. Mount the existing filesystems, review or auto-select the
destinations, and apply the layout.
This guard prevents a new machine from silently adopting the supplied example paths.
MSG
  if [[ -t 0 && -t 1 ]]; then
    echo 'Opening the temporary setup panel now. Select apps and storage, then use Install package in the panel.' >&2
    exec "$SOURCE/setup-server.sh"
  fi
  echo 'Run ./setup-server.sh from an interactive terminal to choose apps and storage first.' >&2
  exit 2
fi
if [[ ! -f /srv/docker/server.env && ! -f "$SOURCE/installed-apps.txt" && ! -f "$SOURCE/configs/app-selection.json" ]]; then
  cat >&2 <<'MSG'
CRITICAL: this is a fresh install and no Docker application selection has been saved.
Choose only the applications to install in the temporary panel, save that selection,
then review storage for those applications before installing.
MSG
  if [[ -t 0 && -t 1 ]]; then
    echo 'Opening the temporary setup panel now. Nothing has been pulled or installed.' >&2
    exec "$SOURCE/setup-server.sh"
  fi
  echo 'Run ./setup-server.sh from an interactive terminal to choose apps first.' >&2
  exit 2
fi
for tool in docker; do command -v "$tool" >/dev/null; done
systemctl show --property=Version --value >/dev/null || { echo 'CRITICAL: this installer requires a running systemd host.'; exit 1; }
[[ $(systemctl show docker.service --property=LoadState --value 2>/dev/null) == loaded ]] || {
  echo 'CRITICAL: this installer requires a systemd-managed Docker Engine service (docker.service), not rootless or Snap-only Docker.' >&2
  exit 1
}
docker info >/dev/null
docker compose version
mkdir -p "$SOURCE/logs"
LOG="$SOURCE/logs/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
trap 'rc=$?; echo "CRITICAL: installer stopped at line $LINENO (exit $rc). Log: $LOG"; exit "$rc"' ERR
exec 9>/run/lock/pi-server.lock
flock -n 9 || { echo 'CRITICAL: another Pi server operation is running'; exit 1; }
python3 "$SOURCE/scripts/storage_guard.py" --installation --manifest "$SOURCE/manifest.json" --only root
echo 'Storage preflight (HDD/media are reported and gated per application):'
python3 "$SOURCE/scripts/storage_guard.py" --manifest "$SOURCE/manifest.json" --json --allow-degraded || true
python3 "$SOURCE/scripts/preflight.py"
echo 'Installing host utilities (no Docker Engine replacement).'
apt-get -o DPkg::Lock::Timeout=300 update
DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 install -y smartmontools nvme-cli unattended-upgrades apt-listchanges curl jq rsync restic dnsutils ca-certificates openssh-client openssl
timedatectl set-ntp true
python3 "$SOURCE/scripts/prepare.py" "$SOURCE"
python3 /srv/docker/scripts/storage_guard.py --only root
python3 /srv/docker/scripts/host-setup.py
systemctl daemon-reload
systemctl enable docker.service
systemctl enable --now pi-storage-watch.timer pi-storage-metrics.timer
systemctl enable pi-storage-start.service
# Reload applies new dependencies without disrupting existing Docker containers.
# The new ExecStartPre executes on the next Docker start, including normal reboot.
set +e
python3 /srv/docker/scripts/manage.py install --report-dir "$SOURCE/logs"
result=$?
set -e
/srv/docker/status.sh || true
if ! /srv/docker/verify-after-reboot.sh; then
    echo 'DONE - BUT RAN INTO ERRORS: final verification failed; review /srv/docker/logs/verify-report.txt'
    result=2
fi
echo "Logs: $SOURCE/logs; report: $SOURCE/logs/installation-report.txt"
echo 'Reboot verification: sudo /srv/docker/verify-after-reboot.sh'
exit "$result"
