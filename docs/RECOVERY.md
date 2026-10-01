# Recovery from a portable snapshot

Use a trusted portable snapshot only. It contains Compose files, passwords,
private application data and SQL exports. A SHA-256 check detects accidental
corruption; it does not make an untrusted snapshot safe to execute.

Release 7 uses the portable snapshot format for recovery because it carries the
saved layout and application-selection information with it. `backup.sh` now
routes to portable backup; `scripts/restore.sh` is a compatibility wrapper for
portable verification/staging and deliberately refuses the earlier hard-coded
`/mnt/hdd` and `/mnt/media` recovery path. Do not use an old canonical-layout
archive as though it were a portable custom-layout snapshot.

## 1. Verify the snapshot without changing a server

Attach the backup disk to a Linux system and identify the complete snapshot
folder, which contains `COMPLETE`, `checksums.json`, `plan.json`,
`backup.json`, `manifest.json`, `files/` and, when initialized databases were
present, `databases/`.

```bash
python3 /path/to/portable-backup.py verify \
  --snapshot /mnt/backup/pi-server/SNAPSHOT_NAME
```

Do not recover an `incomplete-*` folder. Read `plan.json` before proceeding:
`selected_apps` records the app selection when the backup ran;
`historical_apps` identifies deselected applications whose still-configured
data was retained; warnings identify retired/unconfigured paths that were not
accessed. A missing path is not proof that the data was deleted.

## 2. Stage to a new empty Linux filesystem

The staging destination must be an unused absolute path below a mounted Linux
filesystem. It must not be the active server path, a source path, or an
existing directory. Obtain its actual filesystem UUID with `findmnt`.

```bash
findmnt -no UUID --target /mnt/recovery

# Read-only explanation of the planned staging restore.
python3 /path/to/portable-backup.py restore-plan \
  --snapshot /mnt/backup/pi-server/SNAPSHOT_NAME \
  --destination /mnt/recovery/pi-staging

# This creates the new staging directory; it never overwrites an existing one.
sudo python3 /path/to/portable-backup.py restore \
  --snapshot /mnt/backup/pi-server/SNAPSHOT_NAME \
  --destination /mnt/recovery/pi-staging \
  --destination-uuid RECOVERY_FILESYSTEM_UUID
```

Staging validates every indexed checksum before copying, rejects path traversal
and physical symlinks, verifies each copied file and restores the recorded POSIX
metadata where the filesystem supports it. It produces the recovered `files/`
tree, SQL dumps and `STAGING-RESTORE.json`. Runtime sockets and links are kept
as review metadata rather than activated links.

The command does **not** start Docker, overwrite `/srv/docker`, import SQL,
recreate arbitrary links or format/mount a disk. Keep the original backup and
the staging tree until a separate recovery validation has succeeded.

## 3. Prepare the replacement Pi deliberately

The supported deployment target is a 64-bit ARM Raspberry Pi OS, Debian or
Ubuntu host with systemd, `apt`, Docker Engine and Docker Compose v2. Install
Docker/Compose and mount the production filesystems yourself before using the
package. x86 and non-Debian-family hosts are rejected before installation.

Use the temporary setup wizard on the replacement Pi to select the applications
you want and review fresh storage placements. The wizard does not adopt files,
format disks, or edit fstab. Match each required filesystem to the actual
replacement device and UUID; do not copy an old UUID into the new layout just
to pass a check.

Before moving any staged data into a production path:

1. Keep all application stacks stopped and preserve any surviving data under a
   clearly named separate location.
2. Review `files/` and `databases/` in the staging tree, plus `plan.json`,
   `backup.json` and `STAGING-RESTORE.json`.
3. Choose empty prepared destinations through the storage workflow. Do not
   merge a live library with a database from a different backup point.
4. Use matching application/database image major versions and import each
   logical SQL dump into an empty initialized database under a planned
   maintenance procedure.
5. Preserve the recovered `.env` files and encryption keys with root-only
   permissions. They are needed for services such as n8n, Syncthing,
   Paperless and Vaultwarden to read their prior data.

This package intentionally leaves the final placement and SQL import explicit:
the correct decision depends on the replacement disks, selected apps and the
backup's point in time. Do not start Nextcloud, Paperless, Moodle, Syncthing or
media services until the corresponding database and file data come from the
same consistent snapshot or have been independently verified.

## 4. Validate before relying on the recovered server

After the planned import/placement, use the guarded controls and test real
data:

```bash
sudo /srv/docker/scripts/storage_guard.py
sudo /srv/docker/status.sh
sudo /srv/docker/verify-after-reboot.sh
```

Open an existing Nextcloud file and Paperless document; inspect a Gitea
repository, Moodle course/file and n8n credential without exposing keys; check
Syncthing identity/folder paths; and play an existing video and music track.
Confirm the exact mounts, free space, database health and backup-disk plan.
Then create and verify a new portable snapshot, perform one planned reboot, and
run `verify-after-reboot.sh` again before retiring preserved source data.

## Older non-portable archives

If the only copy is an archive made by a release before Release 7, preserve it
unchanged. Recover it only with the matching release's documented tools in an
isolated staging environment after identifying its original storage layout.
Do not point it at a new custom layout or an unmounted directory. Create a new
portable snapshot as soon as the recovered data has been reviewed.
