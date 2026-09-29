# Portable backups to a future external HDD

The backup feature can stay unconfigured until the external 2 TB HDD is connected. The read-only plan reports that no target is configured. It does not mount, format, repartition, import or delete anything.

On the Pi, select the already mounted backup filesystem in Settings, or copy `configs/portable-backup.json.example` to `/srv/docker/configs/portable-backup.json`. Set its exact filesystem UUID and mount point. `folder` names a directory under that mount. Keep `include_bulk: true` for documents, books, uploads, music and videos as well as application state.

The target must be a different physical disk from every configured production device. A second partition on the NVMe, production HDD or microSD is rejected. The exact mount, UUID, writable state, physical parents and free-space reserve are checked before creating a snapshot. Files are written through an open directory handle on the verified destination, so losing the mount cannot redirect output onto the NVMe mount-point directory.

```bash
sudo /srv/docker/portable-backup.sh plan --json
sudo /srv/docker/portable-backup.sh create --json
sudo /srv/docker/portable-backup.sh verify --backup SNAPSHOT_NAME --json
```

`plan` and `verify` are read-only. `create` takes the server operation lock, stops the managed containers that were running, briefly starts each original SQL database container alone to export its database, stops it, and copies the selected state. The restart in `finally` uses exactly the previously running container IDs. Each application's storage identity is checked again before restart, and database/Redis readiness is checked before its application starts. A missing drive prevents affected services from resuming; the resulting `resume.json` records errors. The program never uses Compose recreation to recover from a backup outage.

Allow a maintenance window: copying large media libraries can take hours, and applications stay stopped while their data is copied. Avoid edits from host programs or other computers during the snapshot. Unmanaged running containers with writable mounts overlapping the selected data are rejected. The derived storage-metrics status file is omitted. A file that changes while being read makes the snapshot fail.

Each successful run creates a new timestamped folder. It never synchronizes deletions, replaces an old backup, or prunes earlier versions. Before copying, the estimate includes all selected files, twice the raw SQL database size for dumps, a 1 GiB margin and the configured free-space reserve. Raw PostgreSQL/MariaDB data directories are excluded; they are represented by SQL dumps. Application state on a relocated SSD is included even when `include_bulk` is false. Only registered server data groups are selected, so unrelated files already on your drives are left out.

The snapshot contains:

- `files/`: normal readable files, arranged under their original path, for example `files/mnt/hdd/Books/` or `files/mnt/ssd/PiServer/appdata/`. No proprietary backup format is needed to copy a document out.
- `databases/`: plain SQL exports for initialized PostgreSQL/MariaDB databases.
- `metadata.jsonl`: original ownership, permissions, timestamps and extended attributes. Symlinks are saved as metadata rather than materialized links; runtime sockets are recorded but not copied.
- `manifest.json`, `backup.json`, `plan.json`, `original-containers.json` and `resume.json`: recovery information, coverage, database image references and restart outcome.
- `checksums.json` and `COMPLETE`: a SHA-256 index and completion record. A failed/interrupted run retains an `incomplete-*` folder and never receives a completion record.

Keep the entire snapshot if you need to restore applications. Copying just `files/` loses ownership, link metadata and SQL exports. Snapshots contain credentials and private server data; the generated directories and files use private permissions where the filesystem supports them.

Ext4 is suitable for a Linux backup disk but is not natively readable by Windows. Read it on Linux or through appropriate filesystem tooling. ExFAT/NTFS can store the ordinary backup files, but Linux names unsupported by the destination cause a failed snapshot, and their native permission model is not used for recovery metadata. Restoration of ownership and extended attributes requires a Linux filesystem such as ext4. The installer never changes your filesystem choice.

## Recovery without the original Pi

Copy `scripts/portable-backup.py` to another Linux machine. Python 3.9+ and the standard `findmnt` command are sufficient for staging recovery; Docker and the old `/srv/docker` installation are not required.

```bash
python3 portable-backup.py verify --snapshot /mnt/backup/pi-server/SNAPSHOT_NAME
python3 portable-backup.py restore-plan --snapshot /mnt/backup/pi-server/SNAPSHOT_NAME \
  --destination /mnt/recovery/pi-staging
sudo python3 portable-backup.py restore --snapshot /mnt/backup/pi-server/SNAPSHOT_NAME \
  --destination /mnt/recovery/pi-staging --destination-uuid RECOVERY_FILESYSTEM_UUID
```

The destination's parent must already be on the intended mounted recovery filesystem. The final destination must not exist. Staging recovery validates every indexed checksum first, rejects path traversal and physical symlinks in snapshots, copies files without overwriting, verifies each copied file, and restores its POSIX metadata. Original/active source paths are rejected as destinations. Existing source directories remain unchanged.

Recovery produces a staged file tree, SQL dumps and `STAGING-RESTORE.json`. Links and runtime sockets remain in `links-and-runtime-files.json` for review. It does not start applications, overwrite production paths, recreate symlinks to arbitrary locations or import SQL automatically. Moving the recovered state into service requires selecting prepared empty data locations, matching image/database versions, importing the SQL dumps into empty databases and configuring the new host's actual mount UUIDs before the normal guarded start. Checksums detect accidental corruption; use backups you trust.

Validation in this package covers fixture snapshots, corruption, path traversal, missing dumps, partial-run handling, exact-ID restart behavior, metadata/link staging and remapped storage classification. Actual USB disk, Linux metadata restoration, Docker maintenance and power-loss recovery still need testing on the Pi.
