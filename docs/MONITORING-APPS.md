# Monitoring, disk health and controlled recovery

These projects add about 992 MiB in memory limits. All persistent data is on the system/NVMe storage configured by the installer. No monitoring service moves bulk files or places a database on the media drive.

| Project | Open | Purpose |
| --- | --- | --- |
| Beszel | `http://PI_LAN_IP:8098` | CPU, RAM, host network and container history; configurable alerts |
| Scrutiny | `http://PI_LAN_IP:8099` | HDD/SSD SMART readings and trends |
| Docker Socket Proxy | Internal only | Restricted read access for approved Docker dashboards |
| Diun | Local log; optional remote notifications | Detect changed image tags without upgrading containers |
| Autoheal / JourneyDocker | Internal only | Restart eligible unhealthy containers, with a restart limit |

## Beszel

The installer creates the first user using `BESZEL_USER_EMAIL` (initially `saeed@pi.local`) and generated `BESZEL_PASSWORD` in `/srv/docker/compose/beszel/.env`. The address is a local login name; change it in Settings when configuring email delivery. The hub and agent use a generated SSH key and local UNIX socket. The post-start hook registers this Pi without replacing existing systems or accounts.

If registration needs to be retried on the Pi:

```bash
sudo python3 /srv/docker/compose/beszel/post-start.py
```

For an existing Beszel account with a changed password, add `/beszel_socket/beszel.sock` as the system Host/IP in the web UI. Select the notification destination and CPU, memory, disk or status alert thresholds in Settings. No external alert destination is assumed or contacted during installation. [Upstream agent setup](https://beszel.dev/guide/agent-installation), [environment options](https://beszel.dev/guide/environment-variables).

The agent uses host networking to measure real host interfaces, but listens only on its local UNIX socket. Docker statistics go through a separate read-only UNIX-socket proxy. The agent never receives the real Docker socket. Whole-drive SMART device mappings are resolved during each managed start from mounted, identity-verified configured disks; SD cards and unavailable optional disks are skipped. NVMe admin ioctls require `SYS_ADMIN`; SATA passthrough requires `SYS_RAWIO`. Only the verified devices are mapped with read permission, with no privileged mode and no whole `/dev` mount. [Beszel SMART support](https://beszel.dev/guide/smart-data).

An unsupported USB bridge can prevent HDD SMART readings. Missing SMART values are unavailable data, not a passing health check. File capacity for external storage remains available in the existing mount-aware storage dashboard. Beszel's root filesystem statistics and Docker data remain independent of an unplugged optional HDD.

## Scrutiny

Scrutiny's omnibus image includes its web UI and InfluxDB; only web port 8099 is published. The SQLite state lives in `/srv/docker/configs/scrutiny`, and InfluxDB history in `/srv/docker/databases/scrutiny-influxdb`. Stop the project before backing up both directories together.

On managed start, `prepare.py` rebuilds `collector.yaml` and device mappings from configured mounts, filesystem identity and `/dev/disk/by-id`. There is no fixed USB disk letter in the package. It supports a machine with only its system SSD and microSD; the microSD is omitted because ordinary SD cards do not expose ATA/NVMe SMART. Collection runs every six hours. Check `configs/scrutiny/verified-devices.json`, the dashboard and container logs after hardware changes. Use `sudo /srv/docker/start-all.sh scrutiny beszel` to refresh device mappings after a disk reconnect.

Add notification URLs under `notify.urls` in `configs/scrutiny/scrutiny.yaml` when a destination is ready. Scrutiny has no built-in user login, so access belongs on the private LAN or tailnet. [Upstream project](https://github.com/AnalogJ/scrutiny), [collector configuration](https://github.com/AnalogJ/scrutiny/blob/master/example.collector.yaml), [notification configuration](https://github.com/AnalogJ/scrutiny/blob/master/example.scrutiny.yaml).

## Docker Socket Proxy

The LinuxServer proxy owns the Docker network `pi-docker-read`, which is internal and has no published API port. Approved containers use `tcp://docker-socket-proxy:2375`. List/inspect, statistics, logs, image metadata, events, version and network reads are enabled. Creation, execution, writes, starts, stops, restarts and filesystem archive APIs are disabled. Reading Docker metadata and logs can still reveal application configuration, so do not connect unrelated apps to this network. [Upstream controls](https://docs.linuxserver.io/images/docker-socket-proxy/).

## Autoheal and JourneyDocker

The request named Autoheal twice, including the JourneyDocker implementation. This package installs one [JourneyDocker controller](https://github.com/JourneyDocker/docker-autoheal), avoiding competing restart loops. It checks every 30 seconds after a three-minute initial delay, monitors only running unhealthy containers carrying `pi.autoheal.nvme=true`, and stops a repeatedly failing container after three restarts within 30 minutes.

A separate API filter rechecks every restart/stop: the container must belong to this package, carry the opt-in label, remain running, and have no privileged/device access or bulk-storage binds. Bind paths are checked against the host mount table; a separate filesystem hidden below a system directory is also refused. The filter exposes only Docker version/ping, filtered list/inspect and permitted restart/stop actions. It cannot create containers, run commands, delete data or start stopped containers. If Docker or host mount verification fails, the action is refused. The storage watcher remains responsible for drive-loss handling. Health recovery is not an image update mechanism.

## Diun

Diun checks source tags every six hours, with two workers and a random delay. `prepare.py` builds its list from manifest source-tag evidence because the actual runtime references are immutable digest pins. Notices append to `/srv/docker/appdata/diun/notifications.log` and the container log; the local file rotates at 1 MiB. The initial observation establishes a baseline. Diun has no Docker socket and cannot replace containers or update images.

Add a notification backend to `/srv/docker/configs/diun/diun.yml` for delivery to a phone or email account. Preserve the existing script notifier if local history is useful. Credentials belong in protected local configuration. Restart with `sudo /srv/docker/start-all.sh diun`, then test the chosen channel using Diun's documented notification-test command. [File provider](https://crazymax.dev/diun/providers/file/), [script notifications](https://crazymax.dev/diun/notif/script/), [notification options](https://crazymax.dev/diun/config/notif/).

Versioned source tags may only announce changes within that tag. For release discovery across versions, deliberately configure Diun `watch_repo` with a bounded `max_tags` and version filter; do not silently move the pinned runtime image. Review upstream release notes and backups before updating the package's digest.

## Verification boundary

Image registry indexes and native `linux/arm64` configs were inspected on 2026-09-29; immutable digests and source references are recorded in `monitoring-image-evidence.json`. Compose syntax and the API-policy/source-tag tests run on Windows. Live Pi installation, Docker health, SMART passthrough, actual alert delivery, and boot/reconnect behavior still require the target machine. A healthy process alone is not proof that every disk or remote notification channel works.
