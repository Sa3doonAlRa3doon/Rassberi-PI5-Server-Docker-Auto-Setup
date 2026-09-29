# Raspberry Pi 5 server package

This folder is generated on Windows and is intended to be copied to the Raspberry Pi. The files are **Linux ARM64 deployment files**; they are not Windows server installers.

Copy the folder to `~/Downloads/Rassberi-PI5-Codes` on the Pi, then run:

```bash
cd ~/Downloads/Rassberi-PI5-Codes
chmod +x install-all.sh start-all.sh stop-all.sh update-all.sh backup.sh verify-after-reboot.sh scripts/*.sh
sudo BIND_IP=192.168.1.50 ./install-all.sh
```

For a new or different machine, start with the temporary private setup panel. It discovers mounted ext4 filesystems without scanning or adopting their files, lets you review/auto-select every application data location, and then installs the selected layout:

```bash
chmod +x setup-server.sh
sudo ./setup-server.sh
```

Open the printed private HTTPS address and enter its one-time access key. Auto select always proposes fresh folders, keeps databases/appdata on an SSD, excludes the configured backup disk, and never formats, partitions, imports, moves or deletes existing files. The optional permanent panel uses private port 8788 after installation. Read [docs/STORAGE-CUSTOMIZATION.md](docs/STORAGE-CUSTOMIZATION.md).

Replace `192.168.1.50` with the Pi's private LAN or Tailscale IPv4 address. Run from the host account `pi5`. The installer refuses wildcard/public binding, non-ARM64 systems, non-Trixie systems, missing Docker/Compose, unsafe NVMe storage, and dangerously low space. If a data disk is missing, its dependent applications are skipped with a clear error; independent applications can continue. Existing application usernames and secrets are preserved.

The installer creates `/srv/docker` on the NVMe and writes per-application secrets to root-only `/srv/docker/compose/<app>/.env`. It creates one Compose project per application. It generates an installation report and per-application logs under the copied project's `logs/` directory. Architecture, Docker and unsafe root storage are critical failures. A missing HDD or microSD blocks only the projects that need that disk, and never triggers data-folder creation on the bare NVMe mount point.

For an already installed server changing to the replacement HDD, use [docs/STORAGE-UPDATE.md](docs/STORAGE-UPDATE.md) and retain the [migration report](docs/STORAGE-MIGRATION-REPORT.md). Rerunning the original installer alone does not replace existing configuration files. The storage updater has a dry run, backs up changed files, checks known file hashes, and preserves secrets and application data.

Resource-heavy and scanning applications are installed and image/build checked but stay on demand by default: Stirling PDF, Jupyter, ONLYOFFICE, Moodle, ChangeDetection.io and NetAlertX. The separate Tailscale Homepage also stays off until it has a real Tailscale address. Start one only when needed:

```bash
sudo /srv/docker/start-all.sh onlyoffice
sudo /srv/docker/stop-all.sh onlyoffice
```

The 41 projects contain 59 containers. The default enabled set has a 12,224 MiB aggregate container cap, leaving the 16 GB Pi operating system and filesystem cache headroom. All configured services total 21,760 MiB, so they are intentionally not started together. The runtime checks the current Docker memory budget before starting an app.

## Storage contract

| Device | Required mount | Contents |
|---|---|---|
| NVMe, approximately 512 GB; root partition `/dev/nvme0n1p2` | `/` | OS, Docker, Compose projects, configs, appdata, caches, databases, logs and scripts |
| Seagate ST1000LM035-1RK172, approximately 1 TB; label `HDD1TB`; ext4 | `/mnt/hdd` | Nextcloud, Paperless, Books, Kiwix, Shared and Uploads |
| microSD, approximately 256 GB; label `MEDIA`; ext4 | `/mnt/media` | Music and Videos |

HDD identity is UUID `a8293b36-2c0e-4852-84fd-92ac7503f4db`; microSD identity remains `17e44bc7-f360-45c4-878b-a7fe7aa45f6e`. The HDD is approximately 931.5 GiB raw and 916 GiB as a filesystem. Actual capacity, used space and free space are read from the live mount; free space is never hardcoded. HDD device letters are not used as persistent identity.

The storage guard runs before directory creation, installation, and every managed start. It verifies UUIDs, mount targets, writable state, free space, symlink/submount redirection, and declared paths. A guarded boot service starts configured projects after checking their individual dependencies. Managed containers use `on-failure:5`, so a daemon or host restart cannot bypass per-application storage checks. A selective monitor stops affected projects when their disk becomes unsafe and can resume previously affected work after the correct filesystem returns. It does not stop the entire Docker daemon merely because one optional data disk is missing.

The table above remains the supplied machine's default. A reviewed version-2 layout can use another mounted SSD, omit the HDD, place bulk files on a larger microSD, or add other ext4 data filesystems. Paths and required UUID mounts are derived from that saved layout instead of fixed drive names. Databases and application state still require SSD storage. Existing populated data moves only through an explicit stop-copy-verify operation; originals remain in place.

Use the provided management scripts for storage-dependent projects. Direct `docker compose up`, `docker start`, or Portainer actions can bypass the host wrapper. `create_host_path: false` prevents creating a missing source directory but does not prove an existing directory is the expected mount. UUID checks, guarded startup, restart policy and monitoring protect the managed path. The HDD's `nofail` mount lets the Pi boot without that disk; it does not authorize HDD applications to start.

All active PostgreSQL databases stay under `/srv/docker/databases/<app>` on the NVMe. No database is placed on the HDD or microSD. Large data is mapped as follows:

```text
/mnt/hdd/Nextcloud
/mnt/hdd/Paperless/{media,consume,export}
/mnt/hdd/Books
/mnt/hdd/Kiwix
/mnt/hdd/Shared
/mnt/hdd/Uploads
/mnt/media/Music
/mnt/media/Videos
```

## Management

```bash
sudo /srv/docker/status.sh
sudo /srv/docker/start-all.sh [app ...]
sudo /srv/docker/stop-all.sh [app ...]
sudo /srv/docker/update-all.sh [app ...]
sudo /srv/docker/backup.sh
sudo /srv/docker/verify-after-reboot.sh
sudo /srv/docker/scripts/disk-health.sh
```

The added projects are Beszel, Scrutiny, Docker Socket Proxy, JourneyDocker Autoheal, Diun, Homebox, Linkding, ChangeDetection.io, PairDrop, Localsendy, Home Assistant, NetAlertX and a second Tailscale-only Homepage. Monitoring and utility details are in [docs/MONITORING-APPS.md](docs/MONITORING-APPS.md) and [docs/UTILITY-ADDITIONS.md](docs/UTILITY-ADDITIONS.md). Portable future-drive backups and standalone recovery are in [docs/PORTABLE-BACKUP.md](docs/PORTABLE-BACKUP.md).

To add this release to the earlier 28-project installation without overwriting secrets or data, follow [docs/UPGRADE.md](docs/UPGRADE.md). Run the downloaded package's `upgrade-server.sh --dry-run` before `--apply`.

`update-all.sh` backs up first, pulls only the pinned Compose images, preserves the set of currently running apps, and never removes volumes. `backup.sh` takes an outage, dumps external PostgreSQL/MariaDB databases logically, captures stopped appdata/configuration, and never copies a live database directory. The default backup is a same-NVMe staging copy; configure a separate destination or encrypted restic repository in `/srv/docker/configs/backup.conf` before treating it as disaster protection. Read `BACKUPS.md` and `docs/RECOVERY.md` before restoring.

## First login and access

Generated passwords are in each root-only `.env`; do not paste them into chat or commit them. Most applications have a first-run setup described in `docs/APPS-STATEFUL.md` or `docs/APPS-UTILITIES.md`. The package does not configure router forwarding or public Internet access. Use a private LAN/Tailscale path and add private HTTPS before using browser features that require a secure context (Vaultwarden, Actual and similar apps).

The package does not install Ollama, Open WebUI, local LLMs, Mailu, a desktop environment, or host DNS changes. Pi-hole binds DNS port 53 only to `BIND_IP`; check the host first and do not blindly disable the Pi's existing resolver.

## Validation boundary

The Windows-side audit reads all 41 Compose files and manifest storage declarations, then checks Compose syntax, Bash/Python/JavaScript syntax, 46 unique ports, ARM64 evidence, resource limits, guarded bind mounts, database isolation, storage-layout safety, backup/recovery behavior and Docker-socket boundaries. This is configuration validation, not a live Pi deployment test. Hardware UUIDs, filesystem write/read tests, SMART passthrough, alerts, real file transfers, Home Assistant discovery, NetAlertX discovery, Tailscale Serve, container health and reboot recovery still require the Pi. Read [STORAGE.md](STORAGE.md) for the per-application map.
