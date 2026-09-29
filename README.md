# Raspberry Pi 5 Server Docker Auto Setup

An ARM64 Docker Compose platform for a Raspberry Pi 5. It installs a storage-aware home server with 41 projects, guarded startup, per-application secrets, monitoring, backups, and a private storage customization panel.

> **Target:** Raspberry Pi OS/Debian Trixie on ARM64, with Docker Engine and Compose available. This repository contains Linux deployment files; it is not a Windows installer.

## Start here

Copy this repository to the Pi, then run the installer from the package directory:

```bash
chmod +x install-all.sh setup-server.sh start-all.sh stop-all.sh update-all.sh backup.sh verify-after-reboot.sh scripts/*.sh
sudo BIND_IP=192.168.1.50 ./install-all.sh
```

Replace `192.168.1.50` with the Pi's private LAN or Tailscale address. The installer refuses wildcard/public binding, non-ARM64 systems, unsupported distributions, missing Docker/Compose, unsafe root storage, and dangerously low free space.

For a new machine, use the temporary setup panel first:

```bash
sudo ./setup-server.sh
```

Open the private address and one-time key printed by the script. The panel discovers mounted filesystems without adopting or changing existing files, lets you review every application location, and can auto-select a safe layout. The optional permanent settings panel runs on private port `8788` after installation.

## Included services

The package contains 41 Compose projects and 59 containers. The default set is capped at 12,224 MiB so a 16 GB Pi retains operating-system and filesystem-cache headroom. The full catalog is intentionally not started together; heavier services start on demand.

| Area | Included projects |
|---|---|
| Core | Nextcloud, Paperless-ngx, PostgreSQL, MariaDB, Redis, Vaultwarden, Gitea, Wiki.js, Moodle, n8n, OnlyOffice |
| Media and files | Jellyfin, Navidrome, Calibre-Web, Kiwix, File Browser, Syncthing, PairDrop, Localsendy |
| Monitoring and safety | Beszel, Scrutiny, Docker Socket Proxy, JourneyDocker Autoheal, Diun, Uptime Kuma, Dozzle |
| Utilities | Home Assistant, Homebox, Linkding, ChangeDetection.io, NetAlertX, Stirling PDF, Jupyter, Portainer, Homepage |
| Network and tools | Pi-hole, SearXNG, Code Server, IT-Tools, CyberChef, Excalidraw, Actual |

The second Tailscale-only Homepage is included as `homepage-tailscale` and stays disabled until a real Tailscale address is configured.

Start or stop a heavy project on demand:

```bash
sudo /srv/docker/start-all.sh onlyoffice
sudo /srv/docker/stop-all.sh onlyoffice
```

## Storage layout

| Device | Mount | Stores |
|---|---|---|
| NVMe SSD, about 512 GB | `/` | OS, Docker, databases, configs, appdata, caches, logs and scripts |
| Seagate HDD, about 1 TB | `/mnt/hdd` | Nextcloud, Paperless, Books, Kiwix, Shared and Uploads |
| microSD, about 256 GB | `/mnt/media` | Music and Videos |

The default data paths are:

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

Databases and application state remain on the NVMe. Before creating paths, installing projects, or starting dependent containers, the storage guard verifies the expected UUID, mount target, filesystem state, free space, writable state, symlink boundaries, and declared paths. If a data disk is absent, only projects that need it are held back; the installer never creates a false `/mnt/hdd` or `/mnt/media` directory on the root disk.

The setup panel supports a different machine with an SSD-only layout, a larger microSD, another HDD, or additional ext4 filesystems. It does not format, partition, import, move, or delete populated files. Read [docs/STORAGE-CUSTOMIZATION.md](docs/STORAGE-CUSTOMIZATION.md).

## Operations

```bash
sudo /srv/docker/status.sh
sudo /srv/docker/start-all.sh [app ...]
sudo /srv/docker/stop-all.sh [app ...]
sudo /srv/docker/update-all.sh [app ...]
sudo /srv/docker/backup.sh
sudo /srv/docker/verify-after-reboot.sh
sudo /srv/docker/scripts/disk-health.sh
```

`update-all.sh` preserves the running set and never removes volumes. `backup.sh` takes an outage, dumps PostgreSQL/MariaDB logically, captures stopped appdata/configuration, and never copies a live database directory. Configure a separate disk or encrypted restic repository before treating backups as disaster protection.

For a replacement HDD or a future portable backup disk:

```bash
sudo ./upgrade-server.sh --dry-run
sudo /srv/docker/portable-backup.sh create
```

See [docs/STORAGE-UPDATE.md](docs/STORAGE-UPDATE.md), [docs/PORTABLE-BACKUP.md](docs/PORTABLE-BACKUP.md), and [docs/RECOVERY.md](docs/RECOVERY.md).

## Documentation

- [Documentation index](docs/INDEX.md)
- [Application setup and first logins](docs/APPS-STATEFUL.md)
- [Monitoring and safety services](docs/MONITORING-APPS.md)
- [Utility applications](docs/UTILITY-ADDITIONS.md)
- [Storage map](STORAGE.md)
- [Published ports](PORTS.md)
- [Backup notes](BACKUPS.md)
- [Upgrade path](docs/UPGRADE.md)
- [Tailscale Homepage](docs/TAILSCALE-HOMEPAGE.md)

## Validation boundary

The Windows-side audit checks all Compose files and manifest declarations, syntax, ports, ARM64 evidence, resource limits, guarded mounts, database isolation, backup/recovery behavior, and Docker-socket boundaries. It does not replace live Pi checks. SMART passthrough, filesystem read/write tests, alerts, real transfers, Home Assistant discovery, NetAlertX discovery, Tailscale Serve, container health, and reboot recovery must be verified on the target device.

The existing dashboard archive remains in [dashboard types/IT SIMPLI+.zip](<dashboard%20types/IT%20SIMPLI%2B.zip>).
