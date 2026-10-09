# Additional Raspberry Pi applications

These are Linux ARM64 Docker projects integrated with the package lifecycle. Image indexes and ARM64 image configurations were checked on 29 September 2026 and are pinned by digest. Configuration validation on Windows does not prove that a service has run on the Pi.

| Project | Private web port | Default startup | NVMe persistent state |
|---|---:|---|---|
| Homebox | 7745 | Enabled | `/srv/docker/appdata/homebox` |
| Linkding | 9090 | Enabled | `/srv/docker/appdata/linkding` |
| ChangeDetection.io | 5000 | On demand | `/srv/docker/appdata/changedetection` |
| PairDrop | 3004 | Enabled | Configuration only; files go to the receiving browser |
| Localsendy | 8100 | Enabled when HDD is verified | `/srv/docker/appdata/localsendy` |
| Home Assistant | 8123 | Enabled | `/srv/docker/appdata/home-assistant` |
| NetAlertX | 20211 | On demand | `/srv/docker/appdata/netalertx` |
| ChronoSnap | 8101 | On demand | `/srv/docker/appdata/chronosnap` |

From the installed package on the Pi:

```bash
sudo /srv/docker/start-all.sh changedetection
sudo /srv/docker/start-all.sh netalertx
sudo /srv/docker/stop-all.sh changedetection netalertx
```

Installation prepares and downloads only the applications selected in the setup/settings page. ONLYOFFICE, Jupyter and Stirling PDF receive boot priority when retained in the saved boot selection; ChangeDetection.io, NetAlertX and ChronoSnap remain on demand by default. Clearing the boot selection is a valid choice and is preserved. A newly selected app cannot be started from Settings until the installer has prepared its `.env` and guarded paths. ChangeDetection includes a private browser sidecar; the whole project has a 1,152 MiB cap. NetAlertX and Home Assistant each have a 1,024 MiB cap. ChronoSnap has a 2,048 MiB cap because ffmpeg video builds are CPU/RAM intensive. The manager checks the aggregate running-container memory caps and leaves at least 2 GiB for the OS. Stop unused applications if that check declines another start.

## Homebox

Register the first account at `http://PI_LAN_IP:7745`, then set `HOMEBOX_ALLOW_REGISTRATION=false` in `/srv/docker/compose/homebox/.env` and restart Homebox through the manager. The generated `HOMEBOX_API_KEY_PEPPER` is a server secret, not an initial user password; preserve it with backups. The SQLite database and uploaded warranty documents/photos stay together on NVMe.

Sources: [upstream Homebox](https://github.com/sysadminsmedia/homebox), [configuration](https://homebox.software/en/configure/).

## Linkding

Use `ADMIN_USER` and `LINKDING_PASSWORD` from `/srv/docker/compose/linkding/.env`. Upstream creates that account only when absent. Its SQLite database, bookmarks and assets are stored on NVMe. This uses the standard image, so Chromium HTML-snapshot archiving is not installed. Tags, read-later, imports/exports and the normal bookmarking interface are available.

Sources: [installation](https://linkding.link/installation/), [initial-account options](https://linkding.link/options/).

## ChangeDetection.io

Use `CHANGEDETECTION_PASSWORD` from the private `.env`. The startup wrapper derives the application's supported `SALTED_PASS` value before invoking the original image entrypoint. Change this password in `.env`, then restart the project; an application-side password change cannot override this deployment setting.

Add watch URLs and your own notification destination in the UI. Basic HTTP fetching works without opening a browser. Choose Chrome/Playwright for JavaScript pages. The bundled ARM64 Sockpuppet browser is reachable only within this project's Docker network and allows one Chrome session at a time. Neither browser API port is published, and it has no application-data, host-device or Docker-socket mount. Its upstream Chrome launcher uses `--no-sandbox` inside the container; it receives no added host capabilities. A successful browser healthcheck verifies its API, not that a particular website can be rendered.

Source: [official Compose example](https://github.com/dgtlmoon/changedetection.io/blob/master/docker-compose.yml), [password implementation at the pinned image revision](https://github.com/dgtlmoon/changedetection.io/blob/09881f8b26aa01a2be66c5f63daf54a79a42b6bd/changedetectionio/flask_app.py), [Sockpuppet browser](https://github.com/dgtlmoon/sockpuppetbrowser).

## PairDrop

Open the same private instance on both devices and accept the transfer on the receiving device. PairDrop is a browser-to-browser sender; it does not persist incoming files on the Pi. There is no server database to back up. Its read-only RTC configuration disables external STUN/TURN servers. Local WebRTC is attempted; WebSocket fallback relays transfers through your Pi when peer connectivity is unavailable. That fallback is readable by the private server and consumes its network bandwidth.

LAN clients visiting this instance can discover one another. Use HTTPS through your private access setup for PWA installation, persistent pairing and other secure-browser features. A successful HTTP check alone does not establish cross-device transfer success.

Source: [PairDrop self-hosting guide](https://github.com/schlagmichdoch/PairDrop/blob/master/docs/host-your-own.md).

## Localsendy

This is the requested [ca-x/localsendy](https://github.com/ca-x/localsendy) project, an independent LocalSend-compatible server with a browser control UI. The upstream workflow also publishes to Docker Hub as `czyt/localsendy`; that authentic mirror is used because the GHCR endpoint rejected anonymous access during verification. The Docker Hub ARM64 image is digest-pinned and identifies upstream version v0.3.2 and commit `11b4f3d970b4ce6e98ae9de8cdffc1430f8b8a40`.

The control UI binds only the configured private `BIND_IP` on port **8100**. It is intentionally unauthenticated, so keep that address accessible only to trusted users. Host networking supports LocalSend UDP multicast discovery and its HTTPS receiver on TCP/UDP **53317**. These protocol listeners use host networking; protect them with the host/network firewall. Tailscale does not transport LAN multicast; use PairDrop for browser transfers across your private remote access arrangement.

Incoming transfers require approval by default. The browser-send request limit is 1 GiB. State, identity, certificates and `localsendy.sqlite3` stay in `/srv/docker/appdata/localsendy` on NVMe. Bulk received files go to `/mnt/hdd/Uploads/localsendy/downloads`, while upload/share staging goes to `/mnt/hdd/Uploads/localsendy/tmp`. The container uses UID/GID **10001**. The installer creates those directories only when the required HDD identity passes its guard; Compose refuses to create missing bind sources. The project uses `on-failure:5` and is included in HDD-loss handling.

The app persists its selected receive directory and may override later environment changes. Keep the chosen receive path under `/transfers/downloads` in the UI. The default `LOCALSENDY_NETWORK_INTERFACES=all` can be narrowed to a LAN adapter in this app's `.env`; persisted interface choices in its UI take precedence.

Sources: [Localsendy configuration/security boundary](https://github.com/ca-x/localsendy), [official registry publication workflow](https://github.com/ca-x/localsendy/blob/11b4f3d970b4ce6e98ae9de8cdffc1430f8b8a40/.github/workflows/docker.yml).

## Home Assistant

This installs **Home Assistant Container**, with no Supervisor or add-on store. Complete onboarding in its UI. The first preparation writes a minimal configuration only when `configuration.yaml` is absent: the HTTP server binds `BIND_IP:8123`, timezone is Asia/Dubai, and the default SQLite recorder stays under `/config` on NVMe with seven days of history. Existing configurations are preserved.

Host networking supports local discovery. The container is not privileged and has no Docker socket, USB device or D-Bus mount. Bluetooth, Zigbee, Thread and similar hardware are not configured automatically; identify the actual adapter and grant only the device or D-Bus access required for that integration. A 120-second stop grace period allows database shutdown. Validate device discovery and the integrations you use on the actual Pi.

Source: [official Home Assistant Container installation](https://www.home-assistant.io/installation/linux#install-home-assistant-container).

## NetAlertX

NetAlertX is installed and starts on demand. On preparation, an `AUTO` scan setting is resolved to the single directly attached RFC1918 network containing `BIND_IP`, using that interface's actual `/20`–`/30` prefix. Broader networks, Tailscale addresses, public addresses and ambiguous/absent adapters leave the scan list empty. Existing manually supplied values are preserved. Review `NETALERTX_SCAN_SUBNETS` in `/srv/docker/compose/netalertx/.env` before starting. Example for your own LAN:

```dotenv
NETALERTX_SCAN_SUBNETS=['192.168.1.0/24 --interface=eth0']
```

Do not copy that example unless it matches your network. Only local ARP/mDNS discovery plugins are enabled; Internet probing plugins are excluded. Restrict any additional scan configuration to networks you own or administer. Set the UI password during first run and configure any desired notification destination yourself. `APP_CONF_OVERRIDE` controls the scan list and backend API token, so these `.env` values take precedence over UI changes.

Host networking is required for Layer 2 discovery. The container drops all capabilities and adds the six upstream requirements: `NET_ADMIN`, `NET_RAW`, `NET_BIND_SERVICE`, `CHOWN`, `SETUID` and `SETGID`. Its root filesystem is read-only; runtime scratch space is a bounded tmpfs. The package does not change host ARP sysctls. The UI binds only `BIND_IP:20211`. The upstream backend also listens on host port **20212** on all interfaces and requires the generated `NETALERTX_API_TOKEN`; protect both ports with your private network/firewall policy.

Source: [official Docker Compose](https://docs.netalertx.com/DOCKER_COMPOSE/), [configuration overrides and subnet scope](https://docs.netalertx.com/DOCKER_INSTALLATION/).

## Backups and Pi-side verification

Stop the complete affected project before copying embedded databases. Include its private `.env`, NVMe appdata/configuration and any related HDD files in the same backup. PairDrop has only server configuration; receiving devices must back up their own files. The browser sidecar is disposable.

On the Pi, verify container health and first login, then actually perform a small Localsendy upload/download, a PairDrop transfer between two devices, a watch check/notification, a Home Assistant integration discovery, and a NetAlertX LAN discovery. Verify missing-HDD behavior before relying on unattended Localsendy operation. None of those device-level checks can be established by Compose validation on Windows.
