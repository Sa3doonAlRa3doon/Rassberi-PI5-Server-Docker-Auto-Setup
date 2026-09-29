# Recovery procedure

Use trusted backups only. These archives contain executable scripts, Compose files, passwords and private application data. A checksum detects corruption; it does not authenticate a malicious backup.

The automatic restore supports a **fresh empty `/srv/docker`**, preserved original `.env` credentials, the same database image major versions, and already prepared/mounted production disks. It will not delete or overwrite an existing deployment. It restores logical databases into freshly initialized database containers, then leaves all application stacks stopped. It does not reinstall the OS or overwrite `/etc`.

## 1. Obtain and verify the backup

Use a backup directory containing `COMPLETE`, `SHA256SUMS`, `nvme.tar.gz`, `database-map.tsv`, `manifest.json`, and `databases/`. `bulk.tar.gz` exists only when the run included HDD/media data. Read `backup-info.txt` to confirm coverage. Do not recover an `.incomplete-*` directory as a successful backup.

If the copy is in restic, configure the original repository and password on the replacement host, inspect `restic snapshots`, and restore the selected snapshot to an empty recovery folder. Restic reproduces the archive's original path underneath the target; locate the timestamp directory before continuing.

```bash
sudo bash -c 'source /root/pi-backup.conf; export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE; restic snapshots'
# Replace SNAPSHOT_ID with the selected snapshot; keep its matching config and keys.
sudo bash -c 'source /root/pi-backup.conf; export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE; restic restore SNAPSHOT_ID --target /mnt/recovery'
sudo bash /path/to/project/scripts/restore.sh /path/to/backup/timestamp
```

The last command validates archives without restoring. Use the original generated project scripts if `/srv/docker` was lost. A standalone copied `restore.sh` can perform the first recovery stage; restored runtime scripts supply the common functions afterward. Run it from outside `/srv/docker` so preserving an old server directory cannot move the script you need.

## 2. Prepare the Pi and preserve any surviving state

Install 64-bit Trixie-based Raspberry Pi OS and working ARM64 Docker Engine/Compose on the NVMe as in the original deployment. Install Python 3 and GNU tar/util-linux tools. Mount the existing HDD at `/mnt/hdd` and microSD at `/mnt/media`. Confirm exact filesystems:

```bash
findmnt -o TARGET,SOURCE,FSTYPE,UUID --target /
findmnt -o TARGET,SOURCE,FSTYPE,UUID --mountpoint /mnt/hdd
findmnt -o TARGET,SOURCE,FSTYPE,UUID --mountpoint /mnt/media
```

Expected root is `/dev/nvme0n1p2`. The replacement HDD is expected to have UUID `a8293b36-2c0e-4852-84fd-92ac7503f4db`; the existing microSD UUID remains `17e44bc7-f360-45c4-878b-a7fe7aa45f6e`. Confirm both with `findmnt` before recovery. Do not disable the mount guard just to bypass an error.

If old state exists, stop the backup timer and the managed applications first. Remove old containers using Compose `down` without volume deletion, before moving their bind-mounted data directories. The code below preserves the old directory under a timestamped name; it does not remove any database/user files:

```bash
sudo systemctl stop pi-backup.timer 2>/dev/null || true
sudo /srv/docker/stop-all.sh
sudo bash -c '
  source /srv/docker/scripts/common.sh
  root_required
  lock_server
  for folder in /srv/docker/compose/*; do
    [[ -f "$folder/compose.yml" ]] || continue
    compose "${folder##*/}" down
  done
  mv /srv/docker "/srv/docker-before-restore-$(date -u +%Y%m%dT%H%M%SZ)"
'
```

Recheck the backup source path after moving `/srv/docker`; backups stored underneath it move too. Ensure enough NVMe space for both the preserved copy and the restored deployment. On a completely new server these stop/move steps are unnecessary. Keep preserved state until the restored system passes all checks and a second verified backup exists.

For bulk recovery, each destination below must be absent or empty: `/mnt/hdd/Nextcloud`, `Paperless`, `Books`, `Kiwix`, `Shared`, `Uploads`, `/mnt/media/Music`, and `Videos`. Move any existing folders to deliberately chosen preservation locations on their original disks, checking available capacity first. Do not merge an old live library with a database from another point in time automatically.

## 3. Restore the matching files and databases

```bash
# Full backup with HDD and microSD data:
sudo bash /path/to/project/scripts/restore.sh /path/to/backup/timestamp --confirm-restore --restore-bulk

# NVMe/database recovery while retaining independently verified matching HDD/media files:
sudo bash /path/to/project/scripts/restore.sh /path/to/backup/timestamp --confirm-restore
```

The script refuses nonempty server targets, existing managed containers, incorrect/missing mounts, unsafe archive paths and insufficient free space. It retains numeric ownership and permissions, including `.env` mode 600. It creates fresh database directories from the manifest, starts only each database service, imports its dump, and stops the service again. PostgreSQL uses `pg_restore --no-owner --no-acl --exit-on-error`; MariaDB imports through the matching `mariadb` client. No raw live database files are copied. Do not change database major versions during recovery.

Missing dumps for applications that were never initialized are reported as warnings. Those applications must be initialized separately before being enabled. On any failure, preserve the partial recovery for inspection and inspect `docker compose logs db`; the script never retries by deleting database files. Move that partial recovery aside before attempting a fresh restore.

Do not start Nextcloud, Paperless or Moodle until their database and HDD files are from the same consistent backup or the surviving files have been validated. A restore without `--restore-bulk` does not reconstruct documents, courses, books or media. Do not create empty replacement libraries and assume their contents can be regenerated from database metadata.

## 4. Reapply host protection, then start deliberately

Inspect the restored `.env` files locally with a root-only editor. If the Pi's LAN address changed, update `BIND_IP`, `SERVER_IP` and any application-specific trusted URL/domain configuration without changing saved passwords or encryption keys. Restored appdata may also store URLs independently of `.env`. Avoid printing secret files into shared logs.

On the replacement OS, install the same host utilities and reinstate the mount guards/security updates before starting applications:

```bash
sudo apt-get update
sudo apt-get install -y smartmontools nvme-cli unattended-upgrades apt-listchanges curl jq rsync restic dnsutils ca-certificates
sudo timedatectl set-timezone Asia/Dubai
sudo timedatectl set-ntp true
sudo python3 /srv/docker/scripts/storage_guard.py
sudo python3 /srv/docker/scripts/host-setup.py
sudo systemctl daemon-reload
sudo systemctl enable docker.service
sudo systemctl enable --now pi-storage-watch.timer pi-storage-metrics.timer
sudo systemctl enable pi-storage-start.service
```

Host setup preserves existing settings and can stop for an existing conflicting managed file; inspect that conflict rather than overwriting it. Reconfigure Tailscale on the host separately if the OS was replaced. The backup does not contain Tailscale login state, host SSH keys, or host DNS configuration.

Moodle has a local ARM64 image; rebuild it from its restored Dockerfile before starting that application if the image was lost:

```bash
sudo bash -c 'source /srv/docker/scripts/common.sh; compose moodle build app'
```

Review `/srv/docker/enabled-apps.txt`. Restore does not automatically resume applications that were deliberately stopped. `start-all.sh` starts the configured enabled set; compare it with the backup's `original-containers.txt` and your maintenance records before using it.

```bash
sudo /srv/docker/start-all.sh
sudo /srv/docker/status.sh
sudo /srv/docker/verify-after-reboot.sh
```

## 5. Verify actual recovery before retiring old copies

Log into the restored applications. Download and open an existing Nextcloud file; open a Paperless document and archive; check a Moodle course/file, Gitea repository, and n8n credentials without exposing keys. Confirm Syncthing device identity and folder paths before resuming synchronizations. Play an existing Jellyfin video and Navidrome track. Check Pi-hole DNS from another LAN client and confirm the Pi itself can resolve domains independently. Verify container health, disk free space, the exact mounts and the backup location.

Take a new external backup after successful recovery, validate it, reboot once during a maintenance window, then run `sudo /srv/docker/verify-after-reboot.sh` again. Re-enable the optional backup timer only after its destination, credentials, schedule and space reserve are verified. Keep a written record of the restore test and the backup timestamp tested.
