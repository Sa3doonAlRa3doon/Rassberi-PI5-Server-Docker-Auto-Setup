# Storage setup and later customization

Run `sudo ./setup-server.sh` from the downloaded package before the first install. It starts a temporary HTTPS service on one private IPv4 address, prints a random access key and shuts itself down after completion, Ctrl+C or two idle hours. Its self-signed certificate fingerprint is printed for comparison. It never binds a wildcard/public address.

The discovery page reads Linux block metadata, exact mount identity, filesystem type, UUID, writable state, device kind and free space. It does not enumerate user folders during automatic selection, mount a filesystem, write an fstab entry, format, partition, import or delete anything. Unmounted drives are shown as unavailable until the owner mounts their existing filesystem deliberately.

Auto select follows these rules:

- Databases and application state use a writable mounted SSD. The OS SSD can hold them.
- Bulk documents/media prefer a mounted HDD; media can prefer a mounted microSD. With only an SSD and larger microSD, app state stays on the SSD and bulk/media can use the selected microSD.
- The configured backup UUID and every ineligible drive are excluded.
- Every proposed destination is a new timestamped `PiServer` namespace. Existing folders are never adopted automatically.

Review includes every canonical data group exactly once. Destinations cannot overlap another group, an active source, the backup disk or the fixed storage-metrics control directory. The guard rechecks the exact filesystem UUID and mount at plan, directory creation, copy, configuration commit and application restart.

Changing a populated location requires the visible “Copy existing data” option. Affected managed containers have restart disabled and are stopped application-first; files are copied with ownership, ACLs, hard links and xattrs, then compared with a dry-run checksum/itemized pass. The package switches paths only after verification. Original source files are retained. A recovery copy of changed configuration and the container inventory is stored under `/srv/docker/backups/layout-<UTC>/`. Non-running applications remain stopped.

After installation, enable the permanent private panel:

```bash
sudo python3 /srv/docker/scripts/install-settings-service.py
sudo cat /srv/docker/configs/settings-private/access-key
```

Open `https://PI_PRIVATE_IP:8788`. The service uses its own root-only access key and self-signed TLS certificate. It can select which Docker applications are installed, choose which installed apps start at boot, plan guarded storage changes, configure a future backup drive and start/stop one app through the same manager. Storage groups are shown only for selected applications. Private config files and operation logs are never returned by the API.

Custom layouts preserve existing `/etc/fstab`; the panel does not invent persistent mounts. Before relying on an external path after reboot, create a reviewed UUID-based fstab/systemd mount yourself and verify it with `findmnt --verify`. Missing mounts leave their dependent applications stopped rather than writing into the bare mountpoint on the OS disk.

