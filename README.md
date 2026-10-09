# Raspberry Pi 5 Server Docker Auto Setup

A storage-aware Docker Compose server package for a Raspberry Pi 5. It offers 41 ARM64 projects, but a new installation pulls and prepares only the apps the owner selects. It also provides guarded storage, generated per-app secrets, monitoring, backups, a private setup wizard, and a permanent settings panel.

> **Supported targets:** 64-bit ARM Debian-family Linux with systemd, `apt`, Docker Engine and Docker Compose v2: Raspberry Pi OS, Debian, or Ubuntu. The supplied profile is a Raspberry Pi 5. x86 and non-Debian-family Linux hosts are rejected before installation.

## What this package does

- Installs the Compose projects described in `manifest.json` under `/srv/docker`.
- Keeps PostgreSQL, MariaDB, SQLite and application state on the selected writable SSD.
- Keeps large documents, books, ZIM files, shared files, music and videos on selected bulk-storage mounts.
- Verifies filesystem identity, mount points, free space and writable state before creating paths or starting dependent projects.
- Generates root-only `.env` files without replacing existing credentials.
- Generates a root-only `app passwords.txt` inventory in the downloaded folder and `/srv/docker` for selected apps; each app receives its own bootstrap credential.
- Starts ONLYOFFICE, Jupyter and Stirling PDF at boot as requested, with their dependencies and verified storage ready first; other heavy or scanning applications remain on demand so the host can be tuned.
- Provides guarded update, backup, restore, storage migration and upgrade tools.

## Release 8 changes

Release 8 makes the first download select-only by default:

- Running `sudo ./install-all.sh` from an interactive terminal on a new machine now opens the temporary setup panel before Docker is required, pulled, or started. Choose only the apps you want, save the selection, review storage, and press **Install package** in that panel.
- `sudo ./select-apps.sh` also works directly in the downloaded folder if you prefer the terminal. It writes the same saved selection used by the panel; app dependencies are included automatically.
- The temporary panel rejects **Install package** until both the app selection and reviewed storage layout are saved, with a clear in-page message instead of a hidden installer-log failure.
- Uses a manual release gate so code changes are applied only from a published, newer package.
- Supports a different machine with a different combination of SSDs, HDDs, microSD cards and additional ext4 filesystems.

The storage table below describes the supplied Pi's starting profile. It is a changeable default, not a hardware requirement.

## Release 9 changes

The first-run panel now follows the order a new owner needs:

1. **Storage roles first:** choose the primary SSD/NVMe, bulk-file disk and media disk from the mounted filesystem list. The panel checks UUID, mount state, filesystem and writable status; it never formats a disk or changes `fstab`.
2. **Applications second:** every app card explains its purpose, declared RAM budget, storage class and declared destinations. Dependencies are shown as part of the saved selection.
3. **Review before install:** app destinations are generated only for the apps selected. The **Install selected package** action stays disabled until both the app selection and reviewed layout exist.

The panel does not pull Docker images while the owner is browsing, choosing storage or reading app details. It never downloads every image to estimate disk usage. Before a pull, it reports the honest planning state: persistent data is either SSD/appdata-only or data-dependent bulk storage; the exact image size becomes known only for an image the owner selected and the installer pulls. Unselected projects are not prepared, pulled or started.

## Release 10 changes

After preparation, the installer writes a root-only `app passwords.txt` file in
the downloaded package and `/srv/docker`. It lists selected applications,
private URLs, usernames, generated bootstrap credentials and the required
first-login action. Each application receives a different random credential;
there is no shared password across the server. The file is ignored by Git,
preserved during upgrades, and never returned by the settings API.

Applications do not share a common password-change mechanism. Entries marked
`FIRST_LOGIN_PASSWORD` must be changed in the application's account settings
immediately after the first login. Applications with a first-run account wizard
are marked `NO_GENERATED_PASSWORD` and require account creation there. Database
passwords, encryption keys and admin tokens are included for recovery context
but are marked `INTERNAL_SECRET` or `ADMIN_TOKEN`; they are not web-login
passwords and must not be changed casually.

## Release 11 changes

The re-verification pass corrected the planning metadata for the eight multi-container applications whose cards previously showed an unknown RAM budget. Their declared values now match the sum of the Compose memory caps (Nextcloud 1,504 MiB, ONLYOFFICE 4,352 MiB, Wiki.js 640 MiB, Moodle 1,280 MiB, Gitea 640 MiB, n8n 1,152 MiB, Paperless 1,376 MiB and Vaultwarden 320 MiB). Every application card now shows a concrete planning value before an image is pulled; this is a cap for scheduling, not a promise of actual runtime usage. The credential inventory now also states clearly that its values are bootstrap values; changing a password inside an app requires updating or removing the old inventory line manually.

## Release 12 changes

Selected applications that need a data drive now recover automatically after a
drive was missing during boot. The storage-aware boot service records only the
selected startup applications whose verified directories could not be reached.
`pi-storage-resume.timer` checks the UUID, exact mount point, filesystem,
writability and required directories about once a minute. When those checks
pass, it starts the queued applications in dependency order and removes them
from the queue. Applications that were not selected for installation or boot
are never pulled or started, and an application on a review hold stays stopped.

If a drive is unplugged while an application is already running, the existing
storage watcher still pauses its containers and restores their original Docker
restart policy when the drive returns. No fake `/mnt/hdd` or `/mnt/media`
directory is created on the NVMe root filesystem. If a queued application
still has a port, memory or configuration error after its drive returns, the
attempt is logged for review rather than retried forever; the normal manual
fallback remains `sudo /srv/docker/start-all.sh APP`.

## Release 13 changes

The README now includes one-command installation paths for both a new Pi and an
existing installation. The fresh command still opens the storage and app
selection panel before Docker checks or image pulls, so it remains select-only
and safe for different SSD, HDD and microSD layouts.

## Release 14 changes

The update instructions now follow the repository's current `main` branch
instead of a release-specific download folder. The guarded release gate still
requires a newer published `RELEASE.json` before changing `/srv/docker`.

## Release 16 changes

ChronoSnap has been withdrawn from the package. It is no longer in the
selection panel, manifest, Compose inventory, Homepage, storage map or port
map, and a fresh install will not pull it. The installer report now prints the
individual failed application names and error messages at the end of the
terminal output; the complete per-app logs remain under `/srv/docker/logs`.

## Release 7 changes

Release 7 closes custom-selection and recovery edge cases without deleting existing server data:

- **Selected-only storage:** an SSD-only or otherwise custom layout now checks, renders and creates paths only for selected apps. A deselected app's example HDD or microSD path is ignored rather than becoming a requirement for the selected stack.
- **Deterministic boot order:** ONLYOFFICE, Jupyter and Stirling PDF receive the requested startup priority after Docker and each app's verified storage; dependencies still start before the app that requires them. An intentionally empty boot-start list remains empty.
- **Atomic selection preservation:** the installed-app and startup choices are saved together in `configs/app-selection.json`, with the text lists retained for compatibility. Upgrades preserve this state, including an empty startup selection, as well as app data, databases, `.env` files and storage choices.
- **Safe panel controls:** a selected app that has not yet been prepared by the installer is labelled as needing installation and cannot be started from Settings until its Compose environment exists.
- **Layout-aware recovery:** the portable-backup plan follows the saved layout and app selection, preserves still-configured data from deselected apps for review, and does not touch retired or unconfigured storage paths. It is the supported backup and staged-recovery route for custom layouts and a future backup disk.
- **Legacy archive guard:** `backup.sh` now routes through the portable workflow. `scripts/restore.sh` accepts portable verification/staging commands and refuses unsafe old fixed-layout tar archives instead of extracting them into a custom layout.
- **Linux ARM64 preflight:** fresh installs now accept Raspberry Pi OS, Debian and Ubuntu ARM64 hosts with `systemd` and `apt`; the installer still rejects x86, non-Debian-family hosts and an unavailable Docker daemon.
- **Complete-source backup gate:** the portable backup plan now checks every selected or retained data group, including a bulk drive excluded from file copying, before it creates a snapshot. A missing selected directory or a backup disk that shares any active source disk stops the plan clearly.
- **Restart intent preserved:** storage migration and temporary drive-loss recovery restore every affected container's saved Docker restart policy. A temporary `restart=no` cannot leave an always-on service disabled after the next reboot.
- **Atomic app removal:** Settings stops a removed application's running stack before committing the new selection. If stopping fails, the old selection remains authoritative, so storage monitoring continues to protect that stack.
- **Late database guard:** portable backup rechecks each SQL application's selected storage immediately before treating an absent database container as uninitialized, closing a custom-SSD unplug race.

## Release 6 changes

Release 6 fixes app-selection cleanup: when an installed app is removed from the selection on an existing Pi, its currently running containers are stopped immediately. Its appdata, databases, credentials and files remain untouched and can be selected again later.

## Release 5 changes

- ONLYOFFICE, Jupyter and Stirling PDF are enabled for automatic startup after Docker and verified storage are ready.
- The temporary and permanent settings pages now separate apps to install from apps to start at boot.
- The storage table follows the installed-app selection, so unneeded apps do not force unrelated HDD or microSD destinations.
- select-apps.sh provides the same selection from a Linux terminal; dependencies are included automatically.
- Existing app data, databases, secrets and storage choices remain preserved when an app is deselected or an upgrade is applied.

## Officially fixed in Release 4

Release 4 was the first published **FIXED AND IMPROVED** release. The following issues from the earlier installer and upgrade path remain fixed in the code on `main`:

- **Fresh-install storage selection:** a new machine must use the temporary setup wizard before installation. The installer refuses an unreviewed layout, so it cannot silently write to example `/mnt/hdd` or `/mnt/media` paths.
- **Changeable storage profiles:** the wizard and permanent settings panel support different SSDs, HDDs, microSD cards, additional mounted filesystems, SSD-only machines, and a separate future backup drive. Destinations can be selected manually or proposed by a fresh auto-select profile.
- **Missing-mount protection:** storage identity, mount state, writability, UUID and free space are checked before paths are created, configurations are committed, services are started, or a disk-return resume runs. A missing disk cannot turn into a directory on the NVMe root filesystem.
- **Database placement:** PostgreSQL, MariaDB, SQLite and application state stay on the selected writable SSD. Bulk documents, books, ZIM files, shared files, music and videos can use the reviewed HDD or microSD destinations.
- **Upgrade safety:** upgrades are manual-release-only, reject missing, invalid, same or older releases, and accept hashes from the published release history. Older release 1 installations can therefore receive reviewed fixes without treating genuine local customizations as package files.
- **Data preservation:** the upgrade and apply paths preserve existing secrets, `.env` files, enabled-app choices, application data, databases, bulk files, storage identity and backup settings. They do not delete existing Nextcloud, Paperless or other application data.
- **Port collision handling:** an existing container published on a wildcard address is correctly recognized as belonging to the same project when the configured private `BIND_IP` is checked. This removes the false port-conflict failure seen during re-runs while still rejecting a real conflict from another project.
- **Settings-panel startup:** the permanent settings service waits for its root-only access key and confirms that the service is active before the install step reports success.
- **Interrupted-install recovery:** detached root-shell commands, lock checks and idempotent installers are documented for SSH sessions that close while large ARM64 images are downloading. Completed image layers and services are reused on resume.
- **Replacement and backup-drive handling:** replacement HDD and future backup-drive workflows are guarded, keep backup storage out of active application placement, and provide portable recovery procedures.
- **16 GB memory behavior:** all requested services can be installed, while heavy applications remain on demand and are started only when needed after the aggregate memory check.
- **Monitoring and utility additions:** the published manifest includes the second Tailscale Homepage, Autoheal, Beszel, Scrutiny, Docker Socket Proxy, Diun, Localsendy, NetAlertX, Homebox, Linkding, ChangeDetection.io and PairDrop.

The release marker, upgrade history and source code are committed in this public repository. Runtime credentials, access keys, databases and user files remain on the Pi and are never part of the GitHub package.

## Before you start

You need:

- A 64-bit ARM Debian-family Linux host: Raspberry Pi OS, Debian or Ubuntu. It needs `systemd`, `apt`, Docker Engine and Docker Compose v2. The supplied profile is for a Raspberry Pi 5; x86 and non-Debian-family hosts are rejected.
- Docker Engine and Docker Compose already installed and working.
- A private LAN or Tailscale IPv4 address for `BIND_IP`.
- Internet access for apt packages and container images.
- Enough free space on the NVMe root filesystem for the base stack and image cache.
- Existing data drives mounted as writable ext4 filesystems before selecting them.

Do not expose the installer, settings panel or application ports to the public Internet. The installer rejects wildcard and public binds. Router forwarding, public DNS and TLS certificates are outside this package.

## Minimum and balanced hardware

These profiles apply to the complete Docker package, not just the always-on services. All 41 projects can be installed, while the app-selection page controls which projects are actually prepared and pulled.

| Resource | Minimum for the full package | Balanced for the full package |
|---|---|---|
| CPU | Raspberry Pi 5, Broadcom BCM2712, quad-core 2.4 GHz ARM64 | Same CPU with active cooling |
| RAM | **8 GB**; install all apps but run only a small set together | **12–16 GB**; 16 GB is preferred for the full selected set and the three requested auto-start apps |
| System storage | SSD/NVMe sized for the selected images, databases and appdata; 256 GB is a practical floor | 512 GB NVMe for images, databases, appdata, logs and caches |
| Bulk storage | Only the mounted HDD/microSD needed by the selected apps | About 1 TB HDD for documents/files plus 256 GB microSD for music/videos |
| Backup storage | Separate disk recommended | Separate removable 2 TB-or-larger HDD for portable backups and recovery |
| Power and cooling | Official 27 W USB-C supply and active cooling | Official 27 W USB-C supply and active cooler or fan case |
| Network | Private Ethernet or Wi-Fi with a private LAN/Tailscale IPv4 address | Gigabit Ethernet preferred for transfers and backups |

Storage depends on the applications selected. Databases and application state remain on a writable SSD; bulk data uses the reviewed HDD, SSD or microSD destinations.

## Choose your install path

### One-command fresh install

On a new Raspberry Pi 5, this single command downloads the current package,
opens the temporary setup panel, and starts the guarded installer. Replace the
example address with the Pi's private LAN or Tailscale IPv4 address:

```bash
cd ~/Downloads && (if test -d Rassberi-PI5-Server-Docker-Auto-Setup/.git; then git -C Rassberi-PI5-Server-Docker-Auto-Setup checkout main && git -C Rassberi-PI5-Server-Docker-Auto-Setup pull --ff-only; else git clone https://github.com/Sa3doonAlRa3doon/Rassberi-PI5-Server-Docker-Auto-Setup.git Rassberi-PI5-Server-Docker-Auto-Setup; fi) && cd Rassberi-PI5-Server-Docker-Auto-Setup && chmod +x install-all.sh setup-server.sh && sudo BIND_IP=192.168.4.123 ./install-all.sh
```

If the machine has no saved selection or layout, the command pauses at the
temporary panel before Docker checks or image pulls. Select the storage roles,
choose only the applications you want, review the destinations, and press
**Install package**. It never downloads all application images just to show
their choices. If `Rassberi-PI5-Server-Docker-Auto-Setup` already exists, the command fast-forwards
that checkout instead of deleting it.

### New or different hardware

The setup wizard is the recommended first step when the machine does not match the supplied storage profile.

1. Mount the filesystems yourself at stable paths below `/mnt` or `/media`. The wizard does not mount drives or edit `/etc/fstab`.
2. Copy this repository to the Pi.
3. Choose only the apps you want **before any Docker images are pulled**. The
   easiest route is to start the installer from an interactive terminal; when
   no selection or layout exists, it opens the temporary private setup panel
   instead of installing every app:

```bash
cd ~/Downloads/Rassberi-PI5-Server-Docker-Auto-Setup
sudo ./install-all.sh
```

   Or start the same temporary panel yourself:

```bash
cd ~/Downloads/Rassberi-PI5-Server-Docker-Auto-Setup
chmod +x setup-server.sh install-all.sh start-all.sh stop-all.sh update-all.sh backup.sh portable-backup.sh verify-after-reboot.sh select-apps.sh scripts/*.sh
sudo ./setup-server.sh
```

4. Open the private HTTPS address and one-time key printed by the wizard. This
   panel is temporary: it shuts down after you finish, press `Ctrl+C`, or remain
   idle for two hours. It does not install Docker services or become the
   permanent settings panel.
5. Start on **1. Storage & placement**. Choose the mounted filesystem for the
   primary SSD/NVMe, bulk files and music/videos, then save those storage roles.
   The available choices are limited to identity-verified mounted filesystems.
6. Open **2. Applications**. Select only the Docker apps you need, choose which
   installed apps start at boot, and save the selection. Each card shows its
   purpose, RAM budget, storage class and destination paths. Dependencies are
   included automatically. An empty boot-start list is valid when you want every
   app to start manually. Browsing this page pulls no images.
7. Return to **Storage & placement**. Review each destination, or choose auto-select, then apply the reviewed
   layout. The storage table now covers only the selected applications. The installer
   refuses a fresh install until both the app selection and `configs/layout.json`
   exist, so a new machine cannot silently use the example profile. Deselecting an
   HDD or microSD app means its example path is not created or required on an
   SSD-only machine.
8. Run the installer with the Pi's private address:

```bash
sudo BIND_IP=192.168.1.50 ./install-all.sh
```

Replace `192.168.1.50` with the Pi's private LAN or Tailscale IPv4 address.

If the SSH terminal might close during image pulls, start the install in a
detached root shell and monitor its private log:

```bash
sudo nohup sh -c 'BIND_IP=192.168.1.50 exec ./install-all.sh > /srv/docker/logs/install-console.log 2>&1' </dev/null &
sudo tail -f /srv/docker/logs/install-console.log
```

The first run may take a while while ARM64 images are downloaded and unpacked.
If the session is interrupted, reconnect and run the same detached command only
after checking that no `install-all.sh` process and no `/run/lock/pi-server.lock`
owner remains. The installer is idempotent and reuses completed image layers.

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

### Update to the newest published version

Use this command on an existing installation. It follows `main`, performs a
read-only dry run first, applies only the reviewed newer release, preserves
application data and credentials, and then reconciles the selected projects:

```bash
cd ~/Downloads && (if test -d Rassberi-PI5-Server-Docker-Auto-Setup/.git; then git -C Rassberi-PI5-Server-Docker-Auto-Setup checkout main && git -C Rassberi-PI5-Server-Docker-Auto-Setup pull --ff-only; else git clone https://github.com/Sa3doonAlRa3doon/Rassberi-PI5-Server-Docker-Auto-Setup.git Rassberi-PI5-Server-Docker-Auto-Setup; fi) && cd Rassberi-PI5-Server-Docker-Auto-Setup && chmod +x upgrade-server.sh && sudo ./upgrade-server.sh --dry-run && sudo ./upgrade-server.sh --apply && sudo /srv/docker/install-all.sh
```

If the dry run reports a locally customized file, stop and review that report;
the updater will not silently overwrite it. It rejects the same or an older
release and never deletes Nextcloud, Paperless, database, bulk-file or backup
data.

The same existing-installation upgrade as one copy-paste command is:

```bash
cd ~/Downloads && (if test -d Rassberi-PI5-Server-Docker-Auto-Setup/.git; then git -C Rassberi-PI5-Server-Docker-Auto-Setup checkout main && git -C Rassberi-PI5-Server-Docker-Auto-Setup pull --ff-only; else git clone https://github.com/Sa3doonAlRa3doon/Rassberi-PI5-Server-Docker-Auto-Setup.git Rassberi-PI5-Server-Docker-Auto-Setup; fi) && cd Rassberi-PI5-Server-Docker-Auto-Setup && chmod +x upgrade-server.sh && sudo ./upgrade-server.sh --dry-run && sudo ./upgrade-server.sh --apply && sudo /srv/docker/install-all.sh
```

The upgrade path preserves existing `.env` files, credentials, application data, databases, bulk files, backup settings, and the complete installed/boot selection state in `configs/app-selection.json` (including a deliberately empty boot list). It does not delete old Nextcloud, Paperless or other application data. After `install-all.sh` finishes, enable the permanent settings panel once on an older installation:

```bash
sudo python3 /srv/docker/scripts/install-settings-service.py
sudo cat /srv/docker/configs/settings-private/access-key
```

Open `https://PI_PRIVATE_IP:8788` with the printed access key. The panel lets the owner review storage, plan guarded destination changes, choose on-demand applications, and configure a future backup drive. Read [docs/UPGRADE.md](docs/UPGRADE.md) first.

The updater also checks `RELEASE.json`. It refuses a missing, invalid, or same/older release, so editing a package or leaving a broken package on the server does not silently replace an installed release. A new code release must increment `release_id` and keep the public marker `FIXED AND IMPROVED`. This marker is a release label, not a secret; anything committed to a public GitHub repository is visible.

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

Storage review is scoped to the installed-app selection. If an app is not selected, its default data group is not rendered into the active Compose files or used as a mount requirement. Its old data remains where it is; reselect the app and review its saved/current placement before using it again.

### What remains a safety rule

Databases and application state must stay on a writable SSD. Bulk data can use an HDD or microSD. Every selected drive must already be mounted, writable, have the expected UUID, and have enough free space. A drive used only by a deselected app is not required for the selected stack.

Auto-select proposes fresh timestamped `PiServer` directories. It does not scan user folders, adopt existing folders, import files, format disks, partition disks, edit fstab, or delete data. Moving a populated location requires the visible copy-and-verify action; originals are retained.

The guard checks storage before directory creation, installation, configuration commits, managed starts, and resume after a disk returns. If a drive is missing, only projects that need it remain stopped. Selected boot applications are queued and resumed automatically after the verified drive returns; unselected applications remain stopped. The package never creates a fake `/mnt/hdd` or `/mnt/media` directory on the root filesystem and writes into it.

Read [docs/STORAGE-CUSTOMIZATION.md](docs/STORAGE-CUSTOMIZATION.md), [STORAGE.md](STORAGE.md), and [docs/STORAGE-UPDATE.md](docs/STORAGE-UPDATE.md).

## Included projects

The package contains 41 Compose projects and 59 containers. You can install all of them or select only the projects you need in the setup/settings page. The complete manifest is deliberately not started as one unbounded batch; the manager checks the current memory budget before every start.

| Group | Projects |
|---|---|
| Infrastructure and monitoring | Docker Socket Proxy, Portainer, Homepage, Tailscale Homepage, Uptime Kuma, Dozzle, Beszel, Scrutiny, Diun, JourneyDocker Autoheal |
| Stateful services | Nextcloud, Paperless-ngx, Wiki.js, Gitea, Moodle, n8n, ONLYOFFICE, Vaultwarden, Actual Budget, FreshRSS, Homebox, Linkding |
| Media and files | Jellyfin, Navidrome, Calibre-Web, Kiwix, File Browser, Syncthing, Localsendy, PairDrop |
| Home and network | Home Assistant, NetAlertX, Pi-hole, SearXNG |
| Tools and documents | Code Server, Jupyter, Stirling PDF, IT-Tools, CyberChef, Excalidraw, ChangeDetection.io |

The second Homepage instance is `homepage-tailscale`. It stays disabled until a real Tailscale address is configured.

### Startup defaults

These three requested services receive boot priority after Docker, verified storage and their dependencies are ready:

- ONLYOFFICE
- Jupyter
- Stirling PDF

Moodle, ChangeDetection.io, NetAlertX and Tailscale Homepage remain on demand by default. You can change both the installed-app list and the boot-start list in the permanent settings page. If you clear the boot-start list, Settings preserves that deliberate choice and no selected application is started automatically.

The manager checks the current aggregate memory budget before starting a project. The app page and select-apps.sh never delete existing data when an application is deselected. Read [docs/APPS-STATEFUL.md](docs/APPS-STATEFUL.md) and [docs/UTILITY-ADDITIONS.md](docs/UTILITY-ADDITIONS.md) for first-login and application-specific notes.

## Daily operations

Use the wrappers so storage and dependency checks are applied:

```bash
# Inspect health, mounts, ports and enabled projects
sudo /srv/docker/status.sh

# Start or stop prepared selected projects
sudo /srv/docker/start-all.sh [app ...]
sudo /srv/docker/stop-all.sh [app ...]

# Select the Docker apps to install and start at boot from the terminal
sudo /srv/docker/select-apps.sh

# Pull the explicit pinned images while preserving the running set
sudo /srv/docker/update-all.sh [app ...]

# Check SMART and filesystem health
sudo /srv/docker/scripts/disk-health.sh

# Recheck boot, mounts, containers and health probes
sudo /srv/docker/verify-after-reboot.sh

# Inspect the automatic storage-return queue (normally empty)
sudo test -f /srv/docker/configs/storage-start-pending.json && sudo cat /srv/docker/configs/storage-start-pending.json || echo 'storage-return queue is empty'
sudo tail -n 50 /srv/docker/logs/storage-resume.log
```

Direct `docker compose up`, `docker start`, or Portainer actions can bypass the host storage wrapper. Use the management scripts for storage-dependent applications.

When a Settings app card says **Install package before starting**, save the app selection and run `install-all.sh` first. The panel does not invent its Compose environment or bind directories during a manual start.

## Backups and recovery

The portable backup is the supported backup and staged-recovery path for the current package, especially for custom storage layouts and a future external recovery disk. It takes a consistency outage, exports PostgreSQL/MariaDB logically, captures stopped application state and selected bulk data, and never copies a live database directory.

Before treating a snapshot as disaster protection, configure a separate physical backup disk. A backup disk must be different from the production SSD, HDD and microSD. `backup.sh` is a convenience entry point for the portable workflow. `scripts/restore.sh` stages portable snapshots and refuses the old fixed-layout tar archive procedure.

```bash
# Read-only portable backup plan, then create a snapshot
sudo /srv/docker/portable-backup.sh plan --config /srv/docker/configs/portable-backup.json
sudo /srv/docker/portable-backup.sh create --config /srv/docker/configs/portable-backup.json

# Read the portable backup and restore procedures
less docs/PORTABLE-BACKUP.md
less docs/RECOVERY.md
```

A portable restore stages into a new empty destination and refuses to overwrite existing application data. It does not start applications or import SQL automatically. Read [docs/PORTABLE-BACKUP.md](docs/PORTABLE-BACKUP.md) and [docs/RECOVERY.md](docs/RECOVERY.md).

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
├── RELEASE.json             # published release marker and release_id
├── compose/<app>/          # Compose files and root-only generated .env files
├── configs/                # storage profile, app-selection state, Homepage, monitoring and app configuration
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
- [Validation notes](docs/VALIDATION.md)

## Validation boundary

Windows-side validation checks the 41 Compose projects and manifest declarations, Bash/Python/JavaScript syntax, 46 unique ports, ARM64 image evidence, resource limits, guarded bind mounts, database isolation, storage-layout safety, backup/recovery behavior, and Docker-socket boundaries.

That is configuration validation. The target Pi still needs live checks for filesystem read/write behavior, SMART passthrough, network discovery, real file transfers, alerts, Home Assistant onboarding, NetAlertX discovery, Tailscale Serve, container health, and reboot recovery.


