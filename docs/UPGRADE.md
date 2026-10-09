# Upgrade an existing 28-app installation

This upgrade path targets the same supported host as the installer: 64-bit ARM
Raspberry Pi OS, Debian or Ubuntu with systemd, `apt`, Docker Engine and Docker
Compose v2. x86 and non-Debian-family hosts are rejected before installation.

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

## Release gate

The package is manual-release only. `update-all.sh` updates pinned container images; it does not replace server code. `upgrade-server.sh` reads `RELEASE.json` and accepts only a published package whose `release_id` is higher than the installed release. A missing, invalid, same or older marker stops the code upgrade before files are staged.

`FIXED AND IMPROVED` is the public release marker for this package. It is a release label, not a secret credential. When publishing a real code release, increment `release_id` only after the package has been reviewed and tested. Local customized files are still listed and preserved for review by the existing hash-based upgrade plan.

The dry run is read-only. It accepts an installed file for replacement only when it is absent, already current, or exactly matches the recorded previous package. Unknown/customized files are listed and preserved. Customized systemd units stop the upgrade for review. Apply repeats the plan under the server lock, backs up every replaced file under `/srv/docker/backups/package-upgrade-<UTC>/`, stages the new package, reloads systemd without restarting Docker, and prints the next command.

The updater always preserves storage identity/layout, application `.env` files and credentials, appdata, databases, bulk files, logs, backup settings, review holds, pending storage-return starts, and the user's application selection. The selection is stored atomically in `configs/app-selection.json`; `enabled-apps.txt` and `installed-apps.txt` remain compatibility copies. This preserves a deliberately empty boot-start list instead of silently restoring defaults. `install-all.sh` then installs required host tools, creates only missing guarded directories and environment fields, pulls/verifies new ARM64 images, and reconciles selected projects. The installed-app list is retained. Release 5 adds ONLYOFFICE, Jupyter and Stirling PDF to the startup selection once for older installations; Release 7 gives those selected boot apps deterministic priority after their dependencies and verified storage. Release 12 resumes selected applications automatically after a missing storage drive returns. Later Settings choices are preserved. The remaining heavy and network-scanning apps stay on demand unless selected.

If the deployment uses a custom storage layout, incoming Compose bind sources and manifest paths are rendered through the saved placements before comparison or staging. In Release 7 that rendering and its mount checks are scoped to the installed-app selection: an SSD-only deployment does not acquire a requirement for a deselected app's example HDD or microSD path. Existing data for deselected apps remains untouched. New selected applications initially use NVMe paths; use the permanent Settings panel to move their data after installation if desired.

Use `portable-backup.sh` for a configured recovery disk or any custom-layout backup after the upgrade. In Release 7, `backup.sh` routes through that portable workflow and `scripts/restore.sh` only verifies/stages portable snapshots; the restore wrapper refuses old hard-coded tar archives.

The operation does not format, repartition, delete source data, prune backups or restart the Docker daemon. Review `/srv/docker/logs/installation-report.txt`, open the applications, and run `sudo /srv/docker/verify-after-reboot.sh` after the next planned reboot.

If a selected app needs a drive that is unavailable during reconciliation, the
installer records it as `DEFERRED` and leaves its containers stopped. This is
expected for a missing HDD or microSD and does not make the whole upgrade fail;
the report includes the storage-guard reason. Root-only applications continue,
and the storage-resume service can retry selected boot applications after the
drive is mounted and passes the UUID, filesystem, writable and directory checks.
