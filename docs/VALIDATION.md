# Validation scope

The Release 7 pre-publish gate validates the generated package on the Windows
development host. The manifest currently declares 41 Compose projects, 59
services and 46 unique host-port assignments. The validation suite checks:

- JSON, Bash, Python and browser JavaScript syntax.
- Compose rendering with non-secret test environments.
- ARM64 image declarations/evidence, published-port uniqueness, resource caps,
  private database networks, logging and guarded bind mounts.
- NVMe database placement and selected HDD/microSD bulk paths.
- Missing, wrong, read-only, full, redirected and nested-mount storage cases.
- App-selection saving, dependency expansion, retained empty boot selections,
  selected-only custom-layout rendering and deterministic boot priorities.
- Upgrade preservation, the settings-panel selected-but-unprepared state, and
  portable-backup layout/selection classification, corruption handling and
  staged recovery safeguards.

These development-host checks are valuable regression tests, but they do not
claim that a Pi is installed or that every service has run. The actual supported
target must still pull/build the ARM64 images, verify the local image platform,
pass its real storage UUID and SMART checks, complete application first-run
health checks, verify a configured backup disk, and pass
`sudo /srv/docker/verify-after-reboot.sh` after a planned reboot. Moodle's
source build, USB SMART passthrough, Docker maintenance restart behavior and
power-loss recovery require target-machine testing.
