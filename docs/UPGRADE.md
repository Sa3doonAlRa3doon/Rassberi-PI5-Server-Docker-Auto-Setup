# Upgrade an existing 28-app installation

Copy this complete updated package to a new folder on the Pi. Do not copy it over `/srv/docker` by hand. From the new folder, run:

```bash
chmod +x upgrade-server.sh
sudo ./upgrade-server.sh --dry-run
sudo ./upgrade-server.sh --apply
sudo /srv/docker/install-all.sh
```

On an older installation, enable the permanent settings panel after `install-all.sh` finishes:

```bash
sudo python3 /srv/docker/scripts/install-settings-service.py
sudo cat /srv/docker/configs/settings-private/access-key
```

Open `https://PI_PRIVATE_IP:8788` with the printed access key. The panel uses the new storage and settings code while preserving the existing `.env` files, data and credentials.

The dry run is read-only. It accepts an installed file for replacement only when it is absent, already current, or exactly matches the recorded previous package. Unknown/customized files are listed and preserved. Customized systemd units stop the upgrade for review. Apply repeats the plan under the server lock, backs up every replaced file under `/srv/docker/backups/package-upgrade-<UTC>/`, stages the new package, reloads systemd without restarting Docker, and prints the next command.

The updater always preserves storage identity/layout, application `.env` files and credentials, appdata, databases, bulk files, logs, backup settings, review holds, and the user's `enabled-apps.txt`. `install-all.sh` then installs required host tools, creates only missing guarded directories and environment fields, pulls/verifies new ARM64 images, and reconciles enabled projects. Heavy and network-scanning apps remain on demand according to the retained startup selection; add them in Settings when wanted.

If the deployment uses a custom storage layout, incoming Compose bind sources and manifest paths are rendered through the saved placements before comparison or staging. New applications initially use NVMe paths; use the permanent Settings panel to move their data after installation if desired.

The operation does not format, repartition, delete source data, prune backups or restart the Docker daemon. Review `/srv/docker/logs/installation-report.txt`, open the applications, and run `sudo /srv/docker/verify-after-reboot.sh` after the next planned reboot.
