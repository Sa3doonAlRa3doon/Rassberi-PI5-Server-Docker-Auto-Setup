# Documentation index

Start with the [package overview](../README.md). The supported installation
target is a 64-bit ARM Debian-family Linux host with systemd, `apt`, Docker
Engine and Docker Compose v2: Raspberry Pi OS, Debian or Ubuntu. The supplied
storage profile is for a Raspberry Pi 5; x86 and non-Debian-family hosts are
rejected before installation.

## Install, selection and storage

- [Storage setup and later customization](STORAGE-CUSTOMIZATION.md) explains
  the temporary wizard, selected-app storage groups, SSD-only layouts and the
  permanent Settings panel.
- [Upgrade guide](UPGRADE.md) covers safe package upgrades and preserved
  selection/layout state.
- [Existing Pi storage update](STORAGE-UPDATE.md) is only for the supplied
  replacement-HDD profile.
- [Historical storage migration report](STORAGE-MIGRATION-REPORT.md) records
  that supplied profile and is not a custom-layout recipe.

## Applications and operations

- [Stateful applications](APPS-STATEFUL.md) covers databases, first logins and
  the requested boot-priority apps.
- [Utility, media and file services](APPS-UTILITIES.md) covers libraries,
  transfers and file-access boundaries.
- [Additional Raspberry Pi applications](UTILITY-ADDITIONS.md) covers the
  newer optional projects.
- [Monitoring applications](MONITORING-APPS.md) covers Beszel, Scrutiny,
  Autoheal, Diun and the filtered Docker access path.
- [Tailscale Homepage](TAILSCALE-HOMEPAGE.md) covers the separate tailnet
  dashboard configuration.

## Backup, recovery and validation

- [Portable backup](PORTABLE-BACKUP.md) is the supported layout-aware snapshot
  and future-backup-disk path.
- [Recovery](RECOVERY.md) describes checksum verification and explicit staging
  recovery. It does not automatically overwrite a server or start apps.
- [Validation scope](VALIDATION.md) distinguishes development-host checks from
  target-Pi verification still required before relying on a deployment.
