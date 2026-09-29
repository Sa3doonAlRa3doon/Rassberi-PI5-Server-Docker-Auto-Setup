# Storage migration report

**Prepared:** 2026-09-23  
**Scope:** replace the retired HDD identity while keeping the NVMe root and microSD roles unchanged.

## Result

The active package now expects the Seagate ST1000LM035-1RK172 at `/mnt/hdd` with ext4 UUID `a8293b36-2c0e-4852-84fd-92ac7503f4db`. The existing microSD remains `/mnt/media` with UUID `17e44bc7-f360-45c4-878b-a7fe7aa45f6e`. The root filesystem remains `/dev/nvme0n1p2`. The expected HDD fstab row is `UUID=a8293b36-2c0e-4852-84fd-92ac7503f4db /mnt/hdd ext4 defaults,nofail 0 2`.

No filesystem is formatted, repartitioned, wiped or moved. Databases remain on NVMe below `/srv/docker/databases`; no database path uses the HDD or microSD.

## Services by storage dependency

HDD-dependent projects are **Nextcloud, Stirling PDF, Code Server, Jupyter, File Browser, Moodle, Syncthing, Calibre-Web, Kiwix and Paperless**. Their whole Compose projects are checked before start, and their containers use `on-failure:5` with selective pause/resume monitoring.

microSD-dependent projects are **Jellyfin** (`/mnt/media/Videos`, read-only) and **Navidrome** (`/mnt/media/Music`, read-only).

NVMe-only projects are **Portainer, Homepage, Uptime Kuma, Dozzle, ONLYOFFICE, Wiki.js, Gitea, n8n, IT Tools, CyberChef, SearXNG, Excalidraw, FreshRSS, Actual Budget, Vaultwarden and Pi-hole**. ONLYOFFICE, Jupyter and Stirling PDF now start automatically when selected; the memory guard still stops the boot sequence before the OS is starved. Moodle remains on demand by default. Use the settings page to reduce the boot selection on an 8 GB Pi.

## Exact implementation changes

- `configs/storage.json` centralizes the three identities, models, labels and mount points.
- `storage_guard.py` verifies exact mounts, UUID/filesystem, writable state, NVMe placement, symlink/submount redirection, free-space thresholds and write probes.
- `prepare.py` creates HDD/media directories only after identity checks; missing drives skip only their dependent projects and never create folders on the NVMe mountpoint.
- `manage.py` performs an app-specific guard before every install, start, update or verify operation.
- `docker-storage.conf` gates Docker on the NVMe root only. `pi-storage-start.service` starts enabled apps after Docker, `pi-storage-watch.service` pauses only affected projects, and the metrics timer publishes verified live capacity to the private Homepage sidecar.
- `host-setup.py` updates only the `/mnt/hdd` fstab row and preserves a timestamped host backup. `apply-storage-update.sh --dry-run` validates the reviewed file hashes before any apply.
- The updater may create only the empty NVMe scaffolds `/srv/docker/appdata/storage-metrics` and `/srv/docker/appdata/filebrowser/root`; it never creates a bulk-drive directory while that drive is unverified.
- `migration-files.json` lists the 48 reviewed changed/new package files and their before/after SHA256 values. The pre-update snapshot is `outputs/Pi5-before-1TB-20260923.zip` with baseline hashes in `work/migration-baseline.json`.

## Verification performed on Windows

- 16 safety tests pass in `work/test_safety.py`, including wrong UUID, missing mount, read-only storage, non-NVMe root, low-space, symlink and nested-mount cases.
- All 28 Compose files parse as JSON after their generated comment and all HDD/media binds use `create_host_path: false`.
- All storage-dependent Compose services use `on-failure:5`; all declared databases are on `/srv/docker`.
- Python syntax compiles for the package scripts.
- A recursive scan of the active source package and Desktop copy found **no retired UUID and no persistent device-letter references**. The preserved pre-update snapshot intentionally represents the old release and is not an active configuration.

## Live-Pi checks still required

Run the updater on the Pi and retain its `migration-report.json`. The Pi must still confirm `findmnt` identities, the candidate `/etc/fstab`, real UID/GID ownership, free space, SMART visibility through the USB bridge, Docker container health and one reboot recovery. USB SMART passthrough may report `UNSUPPORTED`; that is a visibility warning rather than proof of disk failure.

