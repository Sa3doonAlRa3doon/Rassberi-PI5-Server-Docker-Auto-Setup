# Storage map and safety rules

All three disks are already prepared. This package never formats, repartitions,
wipes, or changes ext4 reserved blocks. Replacing the HDD changes its identity;
it does not change established application paths or move existing data.

| Disk | Mount | Identity | Purpose |
| --- | --- | --- | --- |
| Micron MTFDHBA512QF NVMe, approximately 512 GB | `/` | Existing root `/dev/nvme0n1p2` | OS, Docker, configurations, all active databases, application state, caches, logs and scripts |
| Seagate ST1000LM035-1RK172 HDD, approximately 1 TB | `/mnt/hdd` | ext4; UUID `a8293b36-2c0e-4852-84fd-92ac7503f4db`; label `HDD1TB` | Bulk documents, books, ZIMs, projects and shared files |
| microSD, approximately 256 GB | `/mnt/media` | ext4; UUID `17e44bc7-f360-45c4-878b-a7fe7aa45f6e`; label `MEDIA` | Existing Music and Videos libraries |

The HDD is approximately 931.5 GiB raw and 916 GiB as a filesystem. These are
reference sizes, not validation constants. Filesystem totals and free space come
from the live mount. UUID and exact mount point are authoritative; label/model are
useful diagnostics. No fixed USB disk letter is required.

The expected HDD fstab entry is:

```fstab
UUID=a8293b36-2c0e-4852-84fd-92ac7503f4db /mnt/hdd ext4 defaults,nofail 0 2
```

The updater validates existing fstab, preserves a timestamped backup and avoids
duplicate mount targets. Root and microSD entries are preserved. It does not unmount
an active drive or mount an unexpected device. `nofail` permits host boot without
the HDD; application startup still requires the matching storage checks.

## Per-application storage map

NVMe paths below are relative to `/srv/docker`. All active PostgreSQL databases
stay under `databases/<app>` on NVMe. This table records the original 28 Compose
projects and their manifest declarations. Read-only (RO) content mounts are noted.

The current package contains 41 projects. Added application state defaults to
`/srv/docker/appdata` or `/srv/docker/databases`; Localsendy bulk transfers default
to guarded HDD uploads. A reviewed custom layout rewrites canonical host paths and
mount dependencies across the manifest and Compose projects. The setup panel never
places a database or application-state group on an HDD or microSD.

| Application | NVMe state/configuration/database | HDD content | microSD content |
| --- | --- | --- | --- |
| portainer | `appdata/portainer`, `configs/portainer` (RO) | — | — |
| homepage | `configs/homepage`, `configs/storage-metrics` (RO), `appdata/storage-metrics` (RO) | — | — |
| uptime-kuma | `appdata/uptime-kuma` | — | — |
| dozzle | `appdata/dozzle` | — | — |
| nextcloud | `databases/nextcloud`, `appdata/nextcloud/redis`, `appdata/nextcloud/html` | `/mnt/hdd/Nextcloud` | — |
| stirling-pdf | `appdata/stirling-pdf`, `appdata/stirling-pdf/logs` | `/mnt/hdd/Uploads/Stirling` | — |
| code-server | `appdata/code-server` | `/mnt/hdd/Shared/Code` | — |
| onlyoffice | `databases/onlyoffice`, `appdata/onlyoffice/data`, `appdata/onlyoffice/cache`, `appdata/onlyoffice/logs`, `appdata/onlyoffice/fonts`, `appdata/onlyoffice/rabbitmq`, `appdata/onlyoffice/redis` | — | — |
| jupyter | `appdata/jupyter` | `/mnt/hdd/Shared/Notebooks` | — |
| wikijs | `databases/wikijs`, `appdata/wikijs/content` | — | — |
| filebrowser | `appdata/filebrowser/database`, `configs/filebrowser`, `appdata/filebrowser/root` (RO) | `/mnt/hdd/Shared`, `/mnt/hdd/Uploads` | — |
| moodle | `databases/moodle`, `appdata/moodle/cache` | `/mnt/hdd/Shared/Moodle` | — |
| syncthing | `appdata/syncthing` | `/mnt/hdd/Shared/Syncthing` | — |
| gitea | `databases/gitea`, `appdata/gitea` | — | — |
| jellyfin | `appdata/jellyfin/config`, `appdata/jellyfin/cache` | — | `/mnt/media/Videos` (RO) |
| navidrome | `appdata/navidrome` | — | `/mnt/media/Music` (RO) |
| calibre-web | `appdata/calibre-web/config`, `appdata/calibre-web/library` | `/mnt/hdd/Books` | — |
| kiwix | `configs/kiwix` (RO) | `/mnt/hdd/Kiwix` (RO) | — |
| n8n | `databases/n8n`, `appdata/n8n` | — | — |
| it-tools | Stateless frontend; preserve browser data as exported files | — | — |
| paperless | `databases/paperless`, `appdata/paperless/redis`, `appdata/paperless/data` | `/mnt/hdd/Paperless/media`, `/mnt/hdd/Paperless/consume`, `/mnt/hdd/Paperless/export` | — |
| cyberchef | Stateless frontend; preserve browser data as exported files | — | — |
| searxng | `configs/searxng`, `appdata/searxng` | — | — |
| excalidraw | Stateless frontend; preserve browser data as exported files | — | — |
| freshrss | `appdata/freshrss/data`, `appdata/freshrss/extensions` | — | — |
| actual | `appdata/actual` | — | — |
| vaultwarden | `databases/vaultwarden`, `appdata/vaultwarden` | — | — |
| pihole | `appdata/pihole` | — | — |

The **10 HDD-dependent projects** are Nextcloud, Moodle, Paperless, Stirling PDF,
Code Server, Jupyter, File Browser, Syncthing, Calibre-Web and Kiwix. The **two
microSD-dependent projects** are Jellyfin and Navidrome. Their whole Compose
projects are guarded together, including supporting databases; database files
remain on NVMe. Other applications gain no unnecessary data-disk dependency.

Gitea repositories stay on NVMe: this update has no measured repository size or
authorized data migration. n8n state and database likewise stay on NVMe. FreshRSS,
Actual Budget and stateless utilities need no new HDD path. No download client or
extra app is installed. No duplicate media, database or Docker-root structure is
created on the HDD. Existing `/mnt/media/Music` and `/mnt/media/Videos` are retained.

## Guarded creation and startup

The central guard verifies the exact mount point, expected UUID, ext4 type,
read/write state, free space, and redirection through symlinks or nested mounts.
It rejects a normal root-filesystem directory in place of either data mount.
Root and Docker data paths are separately checked on the NVMe.

Directories are created only after the matching storage checks pass. A missing
HDD leaves its paths untouched and identifies applications that cannot start.
Independent NVMe applications and microSD media can continue when their own checks
pass. Every Compose bind uses `create_host_path: false` as a second check.

Storage-dependent projects use `on-failure:5`, guarded systemd boot startup and
selective monitoring. This avoids Docker's unguarded reboot/restart path for
those containers. Unrelated projects keep `unless-stopped`. The monitor stops
affected projects if required storage becomes unsafe and can resume work that it
suspended when the correct filesystem returns. It does not format, mount, delete
data, or start an optional project that was deliberately stopped.

Use package management scripts for these projects. Manual Compose, Docker CLI or
Portainer starts can bypass host checks. Periodic monitoring detects and contains
failure; it cannot promise zero I/O errors from sudden physical unplugging. Never
unplug or unmount a disk while containers are writing to it.

Usage thresholds use live values: 70% informational, 80% warning, 90% critical,
95% emergency. Starts on a critical/full filesystem are refused. Installation
also reserves sufficient free space for images/data. SMART queries resolve the
live device behind the validated HDD mount. Unsupported USB passthrough is a
warning, not proof of failed media.

## Ownership and access

The host operator is `pi5`; obtain actual numeric IDs using `id pi5`. PUID/PGID-aware
apps use configured numeric identities. Existing per-app `.env` IDs are preserved;
do not replace them just because the Unix account name changed. `ADMIN_USER` is
an application-login setting, separate from the host account.

PostgreSQL uses **999:999**. Nextcloud and Moodle use **33:33** for writable app
paths. Wiki.js/n8n use **1000:1000**; Jupyter uses **1000:100**. These identities
must not be replaced by recursive `chown pi5:pi5`. Check each UID/path individually.
Typical modes are 0750 for service folders, 0700 for databases/private data, and
0600 for secrets. Readable root-owned scaffold/log/font directories may use 0755.
There is no global 0777 fix.

File Browser deliberately cannot read protected Moodle files if its own UID lacks
access to the 33:33 directory under Shared. Dedicated service directories are not
general shared folders. Upload through the owning app or configure an explicitly
reviewed per-directory group/ACL if shared access is needed. Jupyter files may
similarly need a deliberate access policy if `pi5` does not have UID 1000.

Actual Pi owners, modes and contents were not inspected from Windows. Run the
permission/storage checks on the Pi after applying this update. Existing files
are preserved; mismatches require review, not automatic recursive ownership edits.

## Backups

`/srv/docker/backups` is NVMe staging, not independent disaster protection. A
configured external destination must be a separate physical disk or remote
repository. A folder on the production HDD is not a backup of its only copy.
Backups exclude their own destination, use logical database dumps or cleanly
stopped embedded databases, and preserve a consistent set of data/configuration.
Read `BACKUPS.md` before choosing a destination or restoring. This HDD update
moves no database and no user files.
