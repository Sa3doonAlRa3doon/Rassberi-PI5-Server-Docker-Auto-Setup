# Backups and recovery

Run these commands on the Raspberry Pi after installation. A backup deliberately stops the managed applications while it captures a consistent copy. Plan a maintenance window; a full media backup can take hours on this hardware.

```bash
sudo /srv/docker/backup.sh
sudo cat /srv/docker/backups/last-success
```

The default destination is `/srv/docker/backups/<UTC timestamp>`. This is a recovery copy on the same NVMe, **not protection against NVMe failure, theft or loss of the Pi**. Add a separate physical disk or encrypted remote repository. The prepared HDD and microSD are production data disks, not backup destinations.

## Exactly what is protected

| Content | Default | With `BACKUP_INCLUDE_BULK=1` |
| --- | --- | --- |
| Compose files and secret `.env` files | Included | Included |
| `/srv/docker/configs`, scripts, documents, root management files | Included | Included |
| `/srv/docker/appdata` including stopped SQLite databases and application keys | Included | Included |
| Managed PostgreSQL/MariaDB databases | Logical database dumps | Logical database dumps |
| Raw `/srv/docker/databases` files | Never copied | Never copied |
| HDD Nextcloud, Paperless, Books, Kiwix, Shared, Uploads | **Excluded** | Included |
| microSD Music and Videos | **Excluded** | Included |
| OS installation, `/etc`, Docker image layers, Docker engine state | Excluded | Excluded |
| Data written to custom locations or unmanaged containers/volumes | Excluded | Excluded |

Default backups alone cannot recover Nextcloud user files, Paperless documents, Moodle files in Shared/Moodle, or media after a drive loss. A default database dump and a later copy of user files are not automatically a consistent pair. Enable the bulk option when you need a consistent complete application/file snapshot. Pause any host programs or unmanaged services that also write those folders.

The generated `.env` files are retained verbatim. This preserves database passwords and application keys such as n8n's encryption key, Paperless's secret key, and Syncthing's device identity. Losing these keys can make an otherwise intact database unusable. The backup includes sensitive documents and credentials: directories use root-only permissions; plain local archives are **not encrypted**.

## Consistency, interruption and free-space behavior

The script acquires the same exclusive lock as installation and updates, verifies the exact HDD/microSD UUIDs and NVMe placement, inventories the currently running containers, and stops them. It starts each database container alone, creates its logical dump, then stops it. With application writers stopped, it archives appdata/configuration and optionally HDD/media contents. PostgreSQL uses the database container's matching `pg_dump` version and custom format; MariaDB uses `mariadb-dump` with transaction, routine, event and trigger options. Server database files are excluded from filesystem archives. SQLite and Redis files in appdata are copied only after their containers stop.

The exit trap restores the original running containers on an ordinary success, error, SIGINT or SIGTERM. Services that were already stopped stay stopped. It checks the disks again before resuming. A failed mount check leaves services stopped and reports the problem. SIGKILL, power failure and a Docker daemon restart cannot run a shell trap; inspect the saved `original-containers.txt` and use the guarded management scripts after checking storage. A deliberately stopped container can remain stopped after an interrupted backup, so verify status rather than assuming recovery.

Before the outage, the script estimates input size and database overhead and requires at least 5 GiB of additional free space at the destination. Estimates cannot guarantee capacity under concurrent host writes. Failed runs retain `.incomplete-*` directories for inspection and never replace `last-success`. There is **no automatic retention deletion or prune**. Check capacity regularly and move verified older copies off the NVMe before manually retiring them.

## A separate backup disk

Prepare and mount another physical ext4 disk independently; the installer never formats disks. The following configuration assumes that disk is already mounted at `/mnt/backup`. Use a root-owned file with mode 600:

```bash
sudo install -m 600 /dev/null /srv/docker/configs/backup.conf
sudo nano /srv/docker/configs/backup.conf
```

```bash
BACKUP_ROOT=/mnt/backup/pi-server
BACKUP_MOUNT=/mnt/backup
BACKUP_INCLUDE_BULK=1
```

```bash
sudo /srv/docker/backup.sh
```

The custom destination requires an actual mount, must be below that mount, and must be a different filesystem from all three production filesystems. If the disk is absent, the run fails before applications stop. Use ext4 or another Linux filesystem that preserves root-only permissions; FAT/exFAT is unsuitable for storing unencrypted secrets with those permissions. A different configuration can be passed explicitly: `sudo /srv/docker/backup.sh /root/pi-backup.conf`.

## Encrypted off-device storage with restic

The installer supplies restic. Configure its repository and password file, initialize the repository once, and keep an additional copy of the password somewhere outside this server. The script never prints the password and never initializes or prunes a repository automatically.

This example uses SFTP. Create the remote directory/account first, configure a dedicated SSH key for root, and verify the server's host key through a trusted channel. Test `sudo ssh backup@example-host` before scheduling anything; do not disable SSH host-key checking.

```bash
sudo install -d -m 700 /root/.config/pi-server
sudo bash -c 'umask 077; python3 -c "import secrets; print(secrets.token_hex(32))" > /root/.config/pi-server/restic-password'
```

Add to the root-only `/srv/docker/configs/backup.conf`:

```bash
RESTIC_REPOSITORY=sftp:backup@example-host:/srv/backups/raspberry-pi
RESTIC_PASSWORD_FILE=/root/.config/pi-server/restic-password
# Enable to protect the actual HDD documents and microSD media too.
BACKUP_INCLUDE_BULK=1
```

Initialize once, then back up:

```bash
sudo bash -c 'source /srv/docker/configs/backup.conf; export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE; restic init'
sudo /srv/docker/backup.sh
sudo bash -c 'source /srv/docker/configs/backup.conf; export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE; restic snapshots; restic check'
```

Archives are staged at `BACKUP_ROOT` first and then uploaded after services resume. A full backup may not fit on the source NVMe; use a large separate staging disk when needed. An upload failure preserves the complete local archive but does not advance `last-success`. Restic encrypts its repository; it does not encrypt the local staging files. Compressed timestamped archives trade simplicity for less efficient cross-backup deduplication and longer uploads. For large libraries, a future direct-file restic workflow with coordinated snapshots may be more efficient.

## Scheduling and validation

Start with a manual run and a restore drill. If the project supplies `pi-backup.service`/`pi-backup.timer`, inspect their schedule and enable only when an acceptable outage and destination are established. The local backup is not silently converted into an external backup by a timer. Logs are available through `journalctl -u pi-backup.service`; `last-success` records the destination and whether bulk data was included.

```bash
# Replace the timestamp with a real backup directory.
sudo bash -c 'cd /srv/docker/backups/20260922T180000Z && sha256sum --check SHA256SUMS'
sudo /srv/docker/scripts/restore.sh /srv/docker/backups/20260922T180000Z
```

Without `--confirm-restore`, restore performs checksum/archive validation only. A `COMPLETE` marker means the scripted capture finished; successful checksums mean the saved bytes are intact, not that a full recovery has been tested. Periodically run `restic check --read-data` when bandwidth permits and restore into a spare isolated Pi/disk with the same application versions. Never run a recovery drill against production data.

Read [docs/RECOVERY.md](docs/RECOVERY.md) for fresh-target restoration, database imports, host recovery and a final verification checklist. Official command references: [PostgreSQL pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html), [PostgreSQL pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html), [MariaDB mariadb-dump](https://mariadb.com/docs/server/clients-and-utilities/backup-restore-and-import-clients/mariadb-dump), and [restic backup](https://restic.readthedocs.io/en/stable/040_backup.html).
