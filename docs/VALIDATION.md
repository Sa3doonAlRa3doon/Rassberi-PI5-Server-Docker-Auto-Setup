# Validation record

Windows-side checks completed on 2026-09-22:

- 28 separate Compose projects parsed successfully with Docker Compose v5.5.1 using non-secret test environments.
- 41 container services were checked for `linux/arm64`, `restart: unless-stopped`, explicit memory/CPU caps, JSON log rotation, private database networks, and long bind mounts with `create_host_path: false`.
- 33 host protocol/port assignments were unique. Database services have no published host ports.
- The storage map checked NVMe database roots, HDD document roots, microSD media roots, and read-only media mounts.
- Bash syntax passed for every `.sh` file, and Python compilation passed for every generated `.py` file.
- Fourteen safety tests passed for exact mount identity, missing/read-only/full disks, redirected paths, unhealthy containers, port conflicts, and preservation of existing secrets.

These checks do not claim the Pi is installed. The actual machine must still pull/build the images, inspect the local ARM64 image architecture, pass storage UUID checks, complete first-run app health checks, and pass `verify-after-reboot.sh` after a real reboot. Moodle's source build and application migrations are intentionally verified on the Pi because they cannot be executed on this Windows generation host.
