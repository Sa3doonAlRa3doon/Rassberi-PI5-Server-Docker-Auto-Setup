# Portable backups and recovery

Use the portable backup feature for every new backup. It records the storage
layout selected during setup, checks the exact backup filesystem before a
maintenance window, and can stage recovery on another Linux machine. It does
not format, mount, repartition, import, delete, prune, or overwrite a disk.

The backup disk can stay unconfigured until you add one. A readiness check
then reports that no destination is configured and leaves every container
running.

`update-all.sh` runs this backup gate before it updates images. Configure and
test a portable destination first; an unconfigured or unhealthy backup disk
stops the update before any image pull or service change.

```bash
# Read-only: inspect the configured backup destination and coverage.
sudo /srv/docker/backup.sh --plan --json

# Create one new, timestamped backup after the plan is ready.
sudo /srv/docker/backup.sh --json
```

`backup.sh` is a compatibility command that now runs the portable workflow.
The full command is also available when you need `verify`, `restore-plan`, or
an explicit configuration path:

```bash
sudo /srv/docker/portable-backup.sh plan --json
sudo /srv/docker/portable-backup.sh create --json
sudo /srv/docker/portable-backup.sh verify --backup SNAPSHOT_NAME --json
```

## Configure a future backup disk

In the private Settings panel, choose the already mounted backup filesystem,
set its folder name, decide whether to include bulk files, and save. The
installer never chooses, mounts, formats, or repartitions the backup disk.

You can instead create `/srv/docker/configs/portable-backup.json` from the
example and set the actual mount and filesystem UUID:

```json
{
  "mount": "/mnt/backup",
  "uuid": "YOUR-BACKUP-FILESYSTEM-UUID",
  "folder": "pi-server",
  "include_bulk": true,
  "reserve_gib": 5
}
```

The backup target must be a separate physical disk from every storage device
selected for the server. The program verifies its exact mount, UUID, writable
state, physical parent disks, and free-space reserve before it stops any
managed container. A missing, wrong, read-only, nested, or full target fails
before the maintenance outage begins.

The old `configs/backup.conf` shell configuration and a positional
`backup.sh /path/to/config` argument are retired. They described a fixed
layout and are not read by new releases. Move the destination, bulk choice,
and reserve into `portable-backup.json` or the Settings panel instead.

## What a snapshot contains

Each completed snapshot is an ordinary timestamped folder on the verified
backup disk. It includes readable selected files, logical PostgreSQL/MariaDB
exports, metadata for ownership/permissions/timestamps/xattrs, a checksum
index, the manifest, plan, selected-app list, and container-resume record.
Raw PostgreSQL/MariaDB data directories and runtime sockets are not copied.
Application-local data, configuration, and selected storage directories are
captured after managed writers stop.

With `include_bulk: true`, the selected file/document/music/video locations
are included. With it disabled, the snapshot still includes selected server
state and database exports but does not claim to protect those bulk files.
Unrelated files already present on a production or backup disk are never
selected. Snapshots contain credentials and private data, so keep the backup
disk physically secure.

The program stops only managed containers that were running when the backup
started. It exports initialized SQL databases with their matching containers,
copies files, then resumes the original container IDs after checking storage
again. A failed or interrupted run remains as `incomplete-*` and does not gain
a completion record. It never replaces or prunes an earlier completed
snapshot.

## Verify and stage recovery

Run these on Linux. `verify` and `restore-plan` are read-only. `restore`
requires an exact UUID for an already mounted recovery filesystem and creates
a new staging folder; it never writes to an active application path.

```bash
sudo /srv/docker/scripts/restore.sh verify \
  --snapshot /mnt/backup/pi-server/SNAPSHOT_NAME

sudo /srv/docker/scripts/restore.sh restore-plan \
  --snapshot /mnt/backup/pi-server/SNAPSHOT_NAME \
  --destination /mnt/recovery/pi-staging

sudo /srv/docker/scripts/restore.sh restore \
  --snapshot /mnt/backup/pi-server/SNAPSHOT_NAME \
  --destination /mnt/recovery/pi-staging \
  --destination-uuid RECOVERY_FILESYSTEM_UUID
```

The staging result contains files, SQL dumps, recovery metadata, and a report.
Review it before moving data into a fresh server layout and importing SQL into
matching empty databases. No application starts automatically during recovery.
See [docs/PORTABLE-BACKUP.md](docs/PORTABLE-BACKUP.md) for the full recovery
workflow.

## Older tar backups

Older package versions created `nvme.tar.gz` and optional `bulk.tar.gz`
archives, often below `/srv/docker/backups`. Their restore implementation
assumed a particular old NVMe/HDD/microSD mount layout. The current
`restore.sh` deliberately refuses those archives rather than extracting them
into a custom layout.

Keep an old archive unchanged and use the matching historical release only in
an isolated, reviewed recovery process. Verify the real mounts, UUIDs,
database versions, and free space before attempting that migration. Create a
new portable snapshot once the recovered server is stable; all future recovery
should use that portable snapshot.

## Scheduling

After a successful manual backup, the Settings panel can enable the
`pi-portable-backup.timer` daily schedule. It uses the same checks and never
falls back to a local NVMe copy when the backup disk is unavailable. For a
large library, choose a maintenance window: applications remain stopped while
their selected files are copied.
