# Utility, media and file services

The utility projects are separate Compose projects under `/srv/docker/compose`. Their configs and embedded SQLite/state files remain on the NVMe. The large libraries are mapped only to their assigned data disks.

The replacement 1 TB Seagate HDD keeps `/mnt/hdd` in the supplied profile; UUID-based identity comes from the central storage configuration. Existing content paths are preserved. Custom layouts substitute reviewed paths only for selected apps, so an SSD-only selection does not require these example mounts. Jellyfin and Navidrome continue using the separate microSD in the supplied profile. A missing HDD skips/stops only HDD-dependent selected projects; they use guarded startup and `on-failure:5`. NVMe-only services remain independent. Read `STORAGE.md` for all paths and `docs/STORAGE-UPDATE.md` for the supplied-Pi replacement procedure.

Portainer and Dozzle are the only projects with a Docker socket mount. Portainer needs it to administer Docker; Dozzle needs it to read container logs. Both mounts are documented as host-administrator-equivalent access. Dozzle actions and shell are disabled. Keep both interfaces private.

Jellyfin reads `/mnt/media/Videos` read-only and Navidrome reads `/mnt/media/Music` read-only. Direct play is recommended on the Pi; this package does not pass a transcoding device through or promise that every media format can be transcoded. Kiwix reads `/mnt/hdd/Kiwix` read-only and starts with an empty catalog if no ZIM files are supplied. Copy ZIM archives to that folder and restart Kiwix.

Calibre-Web initializes its application database on the NVMe and is configured for a split library: metadata database on `/srv/docker/appdata/calibre-web/library`, book files on `/mnt/hdd/Books`. Supply a valid Calibre `metadata.db` to the NVMe library path before expecting a populated book catalog. The preparation hook never overwrites an existing database.

File Browser exposes only `/mnt/hdd/Shared` and `/mnt/hdd/Uploads`. It does not expose Nextcloud or Paperless managed directories. Syncthing stores its device identity/index on the NVMe and synchronized files under `/mnt/hdd/Shared/Syncthing`; pair devices explicitly with the Pi address.

File Browser's empty `/srv` scaffold is on NVMe and mounted read-only; its two HDD submounts supply writable content. It does not expose `/`, `/etc`, `/boot`, `/root` or the entire microSD. The Shared tree contains protected service folders: Moodle files are owned by UID/GID 33, so File Browser's PUID need not be able to open that folder. Do not recursively change Shared ownership or modes to bypass that separation.

The host account is `pi5`. PUID/PGID-aware utility containers use configured numeric IDs; existing `.env` values remain authoritative. Jupyter retains image UID/GID 1000:100. Verify `id pi5` before assuming those are the host IDs. Every source directory must be prepared on the correct validated filesystem, never on a bare NVMe mount point.

SearXNG is private and needs outbound Internet access to query upstream search engines. Excalidraw and IT-Tools are stateless frontends; export important browser data to backed-up files. Actual Budget, FreshRSS, Uptime Kuma, Jellyfin and Navidrome have first-run web setup. Jupyter and Stirling PDF receive boot priority only when they are retained in the saved boot selection; on an 8 GB Pi, remove them from that selection while keeping them installed. An empty boot selection stays empty. Jupyter's token and each generated password are in the protected per-app `.env`.

Pi-hole binds DNS port 53 only to `BIND_IP`, with no host networking, DHCP, `NET_ADMIN`, or host DNS rewrite. Test `dig @BIND_IP example.com` before pointing other clients at it. The host keeps an independent resolver path so Docker pulls and system updates do not depend on a broken Pi-hole container.

The images and ARM64 manifest evidence are recorded in `UTILITIES-IMAGE-EVIDENCE.json`. Tags are pinned by digest in generated Compose where available; the installer still inspects the pulled image architecture locally before starting it.
