# Existing Pi storage update

This package updates an already deployed `/srv/docker` installation for the replacement Seagate 1 TB HDD. It does not reinstall applications, move user files, format a disk, or change the NVMe root or microSD.

## Verified storage contract

| Device | Mount | Identity | Role |
| --- | --- | --- | --- |
| Micron NVMe, about 512 GB | `/` | `/dev/nvme0n1p2` | OS, Docker, databases, configs and appdata |
| Seagate ST1000LM035-1RK172, about 1 TB | `/mnt/hdd` | UUID `a8293b36-2c0e-4852-84fd-92ac7503f4db`, ext4, label `HDD1TB` | Nextcloud, Paperless, Books, Kiwix, Shared and Uploads |
| microSD, about 256 GB | `/mnt/media` | UUID `17e44bc7-f360-45c4-878b-a7fe7aa45f6e`, ext4, label `MEDIA` | Music and Videos |

The expected HDD fstab line is:

```fstab
UUID=a8293b36-2c0e-4852-84fd-92ac7503f4db /mnt/hdd ext4 defaults,nofail 0 2
```

The updater changes only the `/mnt/hdd` fstab row. It refuses duplicate mount points, malformed fstab, an unexpected managed systemd file, unknown deployed file edits, symlinked targets, and missing root storage. PostgreSQL and MariaDB data remain below `/srv/docker/databases` on NVMe.

## Apply from a separate directory

Copy the complete updated package to the Pi, outside `/srv/docker`, then run:

```bash
cd ~/Downloads/Rassberi-PI5-Codes
sudo ./apply-storage-update.sh --dry-run
sudo ./apply-storage-update.sh
```

The dry run validates the new HDD UUID, the unchanged microSD UUID, root placement, Compose/Python/Bash syntax, known file hashes, fstab, and the current storage-dependent containers. The apply run creates a timestamped protected backup under `/srv/docker/backups/storage-update-*/`, updates only reviewed files, creates the empty NVMe scaffolds needed for the storage dashboard and File Browser, writes a migration report, reloads systemd and leaves the Docker daemon running. It does not copy or delete data.

Before applying, make sure the replacement HDD is mounted at `/mnt/hdd` and that the expected folders contain the data you intend to use. If a declared folder is missing or empty, the corresponding application is left stopped and listed in `storage-review-required.json`; review and recover data before removing that hold. An unavailable HDD or microSD never blocks unrelated NVMe applications.

## Startup and loss handling

Docker itself checks only the NVMe root filesystem. `pi-storage-start.service` starts enabled applications after Docker, checking each app's own mount requirements. HDD/media projects use `on-failure:5`, so a Docker daemon restart cannot bypass the guard. `pi-storage-watch.timer` checks every minute, pauses only containers that depend on an unsafe drive, and records them in `storage-paused.json`; it resumes those containers after the matching filesystem returns, subject to review holds. It does not stop all Docker services for a missing data drive.

`pi-storage-metrics.timer` publishes verified live capacities for the private Homepage sidecar. It reports N/A when an expected UUID is not mounted. Thresholds are 70% informational, 80% warning, 90% critical and 95% emergency. SMART passthrough failures through a USB bridge are reported as warnings and are not treated as proof that the disk is bad.

After applying, run:

```bash
sudo /srv/docker/storage-status.sh
sudo /srv/docker/status.sh
sudo /srv/docker/verify-after-reboot.sh
```

For a final migration record, retain the updater's `migration-report.json`, the pre-update package snapshot, and the post-update SHA256 inventory. Never use `mkfs`, `fdisk`, `parted`, `wipefs`, or a broad recursive delete as part of this update.
