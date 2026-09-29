# Raspberry Pi 5 Server Docker Auto Setup

A storage-aware Docker Compose server package for a Raspberry Pi 5. It installs 41 ARM64 projects with guarded storage, generated per-app secrets, monitoring, backups, a private setup wizard, and a permanent settings panel.

> **Platform:** Raspberry Pi OS/Debian Trixie on ARM64. These are Linux deployment files. They are not a Windows installer and they are not intended for x86 systems.

## What this package does

- Installs the Compose projects described in `manifest.json` under `/srv/docker`.
- Keeps PostgreSQL, MariaDB, SQLite and application state on the selected writable SSD.
- Keeps large documents, books, ZIM files, shared files, music and videos on selected bulk-storage mounts.
- Verifies filesystem identity, mount points, free space and writable state before creating paths or starting dependent projects.
- Generates root-only `.env` files without replacing existing credentials.
- Starts heavy and scanning applications on demand so a 16 GB Pi is not overloaded.
- Provides guarded update, backup, restore, storage migration and upgrade tools.
- Supports a different machine with a different combination of SSDs, HDDs, microSD cards and additional ext4 filesystems.

The storage table below describes the supplied Pi's starting profile. It is a changeable default, not a hardware requirement.

## Before you start

You need:

- A Raspberry Pi 5 running a Debian Trixie-based ARM64 Raspberry Pi OS.
- Docker Engine and Docker Compose already installed and working.
- A private LAN or Tailscale IPv4 address for `BIND_IP`.
- Internet access for apt packages and container images.
- Enough free space on the NVMe root filesystem for the base stack and image cache.
- Existing data drives mounted as writable ext4 filesystems before selecting them.

Do not expose the installer, settings panel or application ports to the public Internet. The installer rejects wildcard and public binds. Router forwarding, public DNS and TLS certificates are outside this package.

## Choose your install path

### New or different hardware

The setup wizard is the recommended first step when the machine does not match the supplied storage profile.

1. Mount the filesystems yourself at stable paths below `/mnt` or `/media`. The wizard does not mount drives or edit `/etc/fstab`.
2. Copy this repository to the Pi.
3. Start the temporary private setup panel:

```bash
cd ~/Downloads/Rassberi-PI5-Server-Docker-Auto-Setup
chmod +x setup-server.sh install-all.sh start-all.sh stop-all.sh update-all.sh backup.sh verify-after-reboot.sh scripts/*.sh
sudo ./setup-server.sh
```

4. Open the private HTTPS address and one-time key printed by the wizard.
5. Review each destination, or choose auto-select, then apply the reviewed layout.
6. Run the installer with the Pi's private address:

```bash
sudo BIND_IP=192.168.1.50 ./install-all.sh
```

Replace `192.168.1.50` with the Pi's private LAN or Tailscale IPv4 address.

### Existing installation

For normal operations, the installed copy is under `/srv/docker`:

```bash
sudo /srv/docker/status.sh
```

For an older 28-project installation, download this release separately and run the guarded upgrade plan before applying it:

```bash
cd ~/Downloads/Rassberi-PI5-Server-Docker-Auto-Setup
sudo ./upgrade-server.sh --dry-run
sudo ./upgrade-server.sh --apply
sudo /srv/docker/install-all.sh
```

The upgrade path preserves existing `.env` files, credentials, application data, databases, bulk files, backup settings and the enabled-app selection. After `install-all.sh` finishes, enable the permanent settings panel once on an older installation:

```bash
sudo python3 /srv/docker/scripts/install-settings-service.py
sudo cat /srv/docker/configs/settings-private/access-key
```

Open `https://PI_PRIVATE_IP:8788` with the printed access key. The panel lets the owner review storage, plan guarded destination changes, choose on-demand applications, and configure a future backup drive. Read [docs/UPGRADE.md](docs/UPGRADE.md) first.

## Changeable storage

### Supplied default profile

| Device | Mount | Intended contents |
|---|---|---|
| NVMe SSD, about 512 GB | `/` | OS, Docker, databases, configs, appdata, caches, logs and scripts |
| Seagate HDD, about 1 TB | `/mnt/hdd` | Nextcloud, Paperless, Books, Kiwix, Shared and Uploads |
| microSD, about 256 GB | `/mnt/media` | Music and Videos |

The supplied profile's example paths are:

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

### What you can change

The setup wizard and permanent settings panel can use:

- A different mounted SSD for databases and application state.
- A different HDD for bulk documents and shared files.
- A larger microSD for media or other bulk groups.
- An SSD-only machine, with bulk groups placed in reviewed `/srv/pi-data` paths.
- Additional mounted ext4 filesystems.
- A future backup drive that is excluded from automatic application placement.

With only an SSD and a larger microSD, databases and appdata remain on the SSD while media and bulk data can use the selected microSD.

### What remains a safety rule

Databases and application state must stay on a writable SSD. Bulk data can use an HDD or microSD. Every selected drive must already be mounted, writable, have the expected UUID, and have enough free space.

Auto-select proposes fresh timestamped `PiServer` directories. It does not scan user folders, adopt existing folders, import files, format disks, partition disks, edit fstab, or delete data. Moving a populated location requires the visible copy-and-verify action; originals are retained.

The guard checks storage before directory creation, installation, configuration commits, managed starts, and resume after a disk returns. If a drive is missing, only projects that need it remain stopped. The package never creates a fake `/mnt/hdd` or `/mnt/media` directory on the root filesystem and writes into it.

Read [docs/STORAGE-CUSTOMIZATION.md](docs/STORAGE-CUSTOMIZATION.md), [STORAGE.md](STORAGE.md), and [docs/STORAGE-UPDATE.md](docs/STORAGE-UPDATE.md).

## Included projects

The package contains 41 Compose projects and 59 containers. The default enabled set has a 12,224 MiB aggregate container cap. The configured projects total 21,760 MiB, so they are intentionally not started together.

| Group | Projects |
|---|---|
| Infrastructure and monitoring | Docker Socket Proxy, Portainer, Homepage, Tailscale Homepage, Uptime Kuma, Dozzle, Beszel, Scrutiny, Diun, JourneyDocker Autoheal |
| Stateful services | Nextcloud, Paperless-ngx, Wiki.js, Gitea, Moodle, n8n, ONLYOFFICE, Vaultwarden, Actual Budget, FreshRSS, Homebox, Linkding |
| Media and files | Jellyfin, Navidrome, Calibre-Web, Kiwix, File Browser, Syncthing, Localsendy, PairDrop |
| Home and network | Home Assistant, NetAlertX, Pi-hole, SearXNG |
| Tools and documents | Code Server, Jupyter, Stirling PDF, IT-Tools, CyberChef, Excalidraw, ChangeDetection.io |

The second Homepage instance is `homepage-tailscale`. It stays disabled until a real Tailscale address is configured.

### Heavy projects

These are installed and image/build checked, but remain on demand by default:

- ONLYOFFICE
- Stirling PDF
- Jupyter
- Moodle
- ChangeDetection.io
- NetAlertX
- Tailscale Homepage

Start one only when needed, then stop it when finished:

```bash
sudo /srv/docker/start-all.sh onlyoffice
sudo /srv/docker/stop-all.sh onlyoffice
```

The manager checks the current aggregate memory budget before starting a project. Read [docs/APPS-STATEFUL.md](docs/APPS-STATEFUL.md) and [docs/UTILITY-ADDITIONS.md](docs/UTILITY-ADDITIONS.md) for first-login and application-specific notes.

## Daily operations

Use the wrappers so storage and dependency checks are applied:

```bash
# Inspect health, mounts, ports and enabled projects
sudo /srv/docker/status.sh

# Start or stop selected projects
sudo /srv/docker/start-all.sh [app ...]
sudo /srv/docker/stop-all.sh [app ...]

# Pull the explicit pinned images while preserving the running set
sudo /srv/docker/update-all.sh [app ...]

# Check SMART and filesystem health
sudo /srv/docker/scripts/disk-health.sh

# Recheck boot, mounts, containers and health probes
sudo /srv/docker/verify-after-reboot.sh
```

Direct `docker compose up`, `docker start`, or Portainer actions can bypass the host storage wrapper. Use the management scripts for storage-dependent applications.

## Backups and recovery

There are two backup paths:

1. The standard backup takes a consistency outage, logically dumps PostgreSQL/MariaDB, captures stopped appdata and configuration, and never copies a live database directory.
2. The portable backup creates a self-contained archive that can be recovered on another compatible machine or after connecting a replacement drive.

Before treating backups as disaster protection, configure a separate destination or encrypted restic repository. The default same-NVMe staging copy does not protect against loss of the NVMe.

```bash
# Standard managed backup
sudo /srv/docker/backup.sh

# Portable backup
sudo /srv/docker/portable-backup.sh create --config /srv/docker/configs/portable-backup.json

# Read the portable backup and restore procedures
less docs/PORTABLE-BACKUP.md
less docs/RECOVERY.md
```

A fresh-target restore is deliberately explicit and refuses to overwrite existing application data without confirmation. Read [BACKUPS.md](BACKUPS.md), [docs/PORTABLE-BACKUP.md](docs/PORTABLE-BACKUP.md), and [docs/RECOVERY.md](docs/RECOVERY.md).

## Replacement HDD and future backup drive

For the supplied machine's replacement HDD, use the guarded updater. It checks known file hashes, backs up changed configuration, preserves secrets and data, and supports a dry run:

```bash
cd ~/Downloads/Rassberi-PI5-Server-Docker-Auto-Setup
sudo ./upgrade-server.sh --dry-run
sudo ./upgrade-server.sh --apply
```

For a future removable or replacement 2 TB HDD, configure it through the settings panel or portable-backup configuration. The backup disk is excluded from automatic application placement so it remains available for recovery.

## Security and access

- `BIND_IP` must be a private LAN or Tailscale IPv4 address.
- Generated secrets are stored in root-only per-project `.env` files under `/srv/docker/compose/<app>/`.
- The Docker Socket Proxy is used for consumers that need Docker metadata; application containers do not receive an unrestricted Docker socket by default.
- The temporary setup panel shuts down after completion, Ctrl+C, or two idle hours.
- The permanent settings panel uses a root-only access key and self-signed TLS on private port `8788`.
- The package does not configure router forwarding, public DNS, public HTTPS, host DNS replacement, or a desktop environment.
- Pi-hole binds DNS only to `BIND_IP`; check the host resolver and port 53 before enabling it for other clients.

Keep the Pi and its management ports on a trusted LAN or tailnet. Do not commit generated `.env` files, access keys, TLS keys, logs, databases, backups, or runtime state.

## Where files live

After installation:

```text
/srv/docker/
├── compose/<app>/          # Compose files and root-only generated .env files
├── configs/                # storage profile, Homepage, monitoring and app configuration
├── appdata/                # application state on the selected SSD
├── databases/              # PostgreSQL/MariaDB and other database state on the selected SSD
├── scripts/                # guarded management, storage, backup and restore tools
├── systemd/                # boot, storage-watch, settings and backup units
└── logs/                   # installer, operation and verification reports
```

The public repository contains examples and deployment code. Runtime secrets and generated state belong only on the Pi.

## Documentation

- [Documentation index](docs/INDEX.md)
- [Application setup and first logins](docs/APPS-STATEFUL.md)
- [Utility applications](docs/APPS-UTILITIES.md)
- [Monitoring services](docs/MONITORING-APPS.md)
- [Storage customization](docs/STORAGE-CUSTOMIZATION.md)
- [Storage map](STORAGE.md)
- [Replacement HDD update](docs/STORAGE-UPDATE.md)
- [Portable backup](docs/PORTABLE-BACKUP.md)
- [Recovery](docs/RECOVERY.md)
- [Upgrade guide](docs/UPGRADE.md)
- [Tailscale Homepage](docs/TAILSCALE-HOMEPAGE.md)
- [Published ports](PORTS.md)
- [Backup notes](BACKUPS.md)
- [Validation notes](docs/VALIDATION.md)

## Validation boundary

Windows-side validation checks the 41 Compose projects and manifest declarations, Bash/Python/JavaScript syntax, 46 unique ports, ARM64 image evidence, resource limits, guarded bind mounts, database isolation, storage-layout safety, backup/recovery behavior, and Docker-socket boundaries.

That is configuration validation. The target Pi still needs live checks for filesystem read/write behavior, SMART passthrough, network discovery, real file transfers, alerts, Home Assistant onboarding, NetAlertX discovery, Tailscale Serve, container health, and reboot recovery.

The existing dashboard archive remains in [dashboard types/IT SIMPLI+.zip](<dashboard%20types/IT%20SIMPLI%2B.zip>).
