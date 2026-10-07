# Stateful applications

These files target a 64-bit Raspberry Pi 5. No application was deployed on Windows.
The registry checks below verify image availability and architecture; they do not
claim the server has already passed a live Raspberry Pi installation test.

Each application has its own Compose project, an internal database network, and
its own PostgreSQL 17 database on NVMe. Database ports are never published.
Applications with web access also join their own frontend network. Every published
port requires an explicit `BIND_IP`; the installer supplies the Pi's private
address. Each bind mount uses `create_host_path: false` and the host installer
must validate the physical storage UUID before creating or starting HDD paths.
The replacement Seagate 1 TB drive remains `/mnt/hdd` in the supplied profile;
its current identity is defined by the central storage configuration and
documented in `STORAGE.md`. A custom layout may use different reviewed paths,
and a deselected application's HDD data group is not a mount requirement for
the selected stack. Nextcloud, Paperless and Moodle keep their existing content
paths. Their guarded projects use `on-failure:5`, while NVMe-only projects retain
`unless-stopped`. If the HDD is unavailable, only dependent selected projects
are skipped/stopped. Gitea, n8n, Wiki.js, Vaultwarden and ONLYOFFICE acquire no
new HDD dependency.

## Allocation and storage

| Application | Host ports | Total memory ceiling | Permanent application data | PostgreSQL data |
| --- | --- | ---: | --- | --- |
| Nextcloud | 8080 | 1504 MiB | NVMe `/srv/docker/appdata/nextcloud`; files `/mnt/hdd/Nextcloud` | `/srv/docker/databases/nextcloud` |
| ONLYOFFICE, starts at boot by default | 8081 | 4352 MiB | `/srv/docker/appdata/onlyoffice` | `/srv/docker/databases/onlyoffice` |
| Moodle, on demand | 8082 | 1280 MiB | NVMe caches `/srv/docker/appdata/moodle/cache`; files `/mnt/hdd/Shared/Moodle` | `/srv/docker/databases/moodle` |
| Wiki.js | 8084 | 640 MiB | `/srv/docker/appdata/wikijs/content` and PostgreSQL | `/srv/docker/databases/wikijs` |
| Gitea | 3001 web; 2222 SSH | 640 MiB | `/srv/docker/appdata/gitea` | `/srv/docker/databases/gitea` |
| n8n | 5678 | 1152 MiB | `/srv/docker/appdata/n8n` and PostgreSQL | `/srv/docker/databases/n8n` |
| Paperless-ngx | 8087 | 1376 MiB | NVMe index/config `/srv/docker/appdata/paperless`; documents `/mnt/hdd/Paperless/{media,consume,export}` | `/srv/docker/databases/paperless` |
| Vaultwarden | 8089 | 320 MiB | `/srv/docker/appdata/vaultwarden` | `/srv/docker/databases/vaultwarden` |

Always-on stacks in this document total **5632 MiB (5.5 GiB)** of memory ceilings.
This leaves capacity for the other application groups and the host. Ceilings are
limits, not promises of performance under simultaneous load. Keep heavy workflows
small and run heavy optional applications only when needed. ONLYOFFICE now starts at boot by default; disable it in the settings page if the machine is being used for a lighter profile. A process that exceeds
its limit can be killed by the kernel; inspect `docker stats` and the health report.

ONLYOFFICE's official ARM64 instructions specify at least 4 GB RAM, 40 GB free
disk and 4 GB swap. Its application container therefore has a 4 GiB ceiling, plus
256 MiB for the separate database. The installer does not silently create swap.
Check NVMe free space and host memory before starting it. Stop it when finished.
[Official ARM64 requirements](https://helpcenter.onlyoffice.com/docs/installation/docs-community-install-docker-arm64.aspx).

ONLYOFFICE, Jupyter and Stirling PDF receive boot priority after Docker, verified storage and their dependencies are ready. This applies only while they remain in the saved boot-start list; an intentionally empty list stays empty. Use the settings page or `sudo /srv/docker/select-apps.sh` to change the installed-app and boot-start lists. Start or stop any prepared selected application manually with `sudo /srv/docker/start-all.sh APP` and `sudo /srv/docker/stop-all.sh APP`; its persistence remains intact.

## Initial accounts and URLs

Replace `PI_ADDRESS` below with the private address printed by installation.
Protected `.env` files are stored in `/srv/docker/compose/<application>/.env`.
The installer generates the secrets once and preserves existing files on reruns.
Read them locally with `sudoedit`; never paste them into support logs.

The installer also writes a root-only credential inventory at
`/srv/docker/app passwords.txt` and, for a fresh download, beside the package
in the downloaded folder. Read it with:

```bash
sudo cat '/srv/docker/app passwords.txt'
```

The inventory contains only selected applications. `FIRST_LOGIN_PASSWORD`
entries are unique generated bootstrap passwords and must be changed in the
application's account settings immediately after first login. Apps marked
`NO_GENERATED_PASSWORD` use their own first-run account wizard. Database
passwords, encryption keys and admin tokens are labelled separately and are
not ordinary web-login passwords. The `.env` file remains the Compose source
of truth; the inventory is a local convenience copy and is never returned by
the settings API or committed to Git.

| Application | First-run action |
| --- | --- |
| Nextcloud | Open `http://PI_ADDRESS:8080`, use its entry in `app passwords.txt`, then change the password in account security settings. |
| ONLYOFFICE | It is an editing backend without a user-login portal; integrate it into Nextcloud as described below. |
| Moodle | Open `http://PI_ADDRESS:8082`, use its entry in `app passwords.txt`; change the password, replace the placeholder admin email and configure SMTP. |
| Wiki.js | Open `http://PI_ADDRESS:8084` and create the administrator using the setup wizard. Set the canonical site URL. |
| Gitea | Open `http://PI_ADDRESS:3001`; confirm prefilled PostgreSQL details and explicitly create `saeed` under Administrator Account Settings. Public self-registration is disabled. SSH uses host port `2222`. |
| n8n | Open `http://PI_ADDRESS:5678` and create the instance owner. Initial owner creation is not assumed to be automatable through undocumented environment variables. |
| Paperless-ngx | Open `http://PI_ADDRESS:8087`, use its entry in `app passwords.txt`, change the password, then import a small document and verify OCR. |
| Vaultwarden | Use the HTTPS/tunnel procedure below. Authenticate to `/admin` with `ADMIN_TOKEN`, invite your email, then create the invited account. Public registration is disabled. |

All initial HTTP endpoints are private bootstrap interfaces. Tailscale encrypts
network transport, but a browser still needs an HTTPS URL for features such as
WebCrypto. Configure private HTTPS before treating password-manager web access as
ready for normal use. No router forwarding or public proxy is configured.

## Nextcloud and ONLYOFFICE

Nextcloud is pinned to the verified stable 34.0.4 Apache image. Its PHP memory
limit is 256 MiB per request. PostgreSQL and Redis have health checks; the app
waits for both. A separate `/cron.sh` container runs background tasks. In Nextcloud
Administration settings > Basic settings, select **Cron**. Configure SMTP, then
verify uploading and downloading a test file after restarting the stack.

To connect the optional ONLYOFFICE service:

1. Start ONLYOFFICE after checking available RAM/NVMe space.
2. Install the official ONLYOFFICE connector in Nextcloud's Apps interface.
3. In Nextcloud Administration > ONLYOFFICE, set the document-server URL to
   `http://PI_ADDRESS:8081/` and the secret to ONLYOFFICE's `JWT_SECRET`.
4. Set the connector JWT header to `AuthorizationJwt` using the supported setting:

   ```bash
   cd /srv/docker/compose/nextcloud
   sudo docker compose exec -u www-data app php occ config:app:set onlyoffice jwt_header --value=AuthorizationJwt
   ```

   Under advanced addresses,
   use a private address reachable from both containers for the document server
   and `http://PI_ADDRESS:8080/` for Nextcloud. The browser must also reach the
   document server. With HTTPS, both externally used URLs must use HTTPS to avoid
   mixed-content blocking.
5. Nextcloud may block requests to local addresses by default. For this deliberate
   private integration, enable its local-server access setting:

   ```bash
   cd /srv/docker/compose/nextcloud
   sudo docker compose exec -u www-data app php occ config:system:set allow_local_remote_servers --type=boolean --value=true
   ```

6. Open a disposable document, change it, save it, and verify the downloaded file.

ONLYOFFICE explicitly permits private-IP callbacks so it can save into Nextcloud.
JWT remains enabled, metadata IP access remains disabled, and certificate checks
remain enabled. Configure these settings only for a private server. No local AI
inference server, AI provider key, or inference workload is installed.

[Nextcloud image documentation](https://github.com/nextcloud/docker),
[ONLYOFFICE Docker configuration](https://github.com/ONLYOFFICE/Docker-DocumentServer),
[Nextcloud connector instructions](https://github.com/ONLYOFFICE/onlyoffice-nextcloud).

## Moodle build and maintenance

Moodle is built on the Pi from official source **5.2.3**, immutable Git commit
`344232c15336c71b80f9aca8359ce0e0a9f3d116`. The official PHP 8.3.33 Apache and
Composer 2.10.3 base images both contain verified ARM64 manifests. The Dockerfile
installs required PHP extensions and uses the upstream Composer lockfile with
`--no-dev`; it does not run MoodleHQ's developer/testing Compose environment.

The web root is `/var/www/moodle/public`, so the configuration and vendor files
remain outside the web root. PHP application files belong to root and are not
writable by Apache. Persistent files belong to `www-data` (UID/GID 33), and the
database belongs to PostgreSQL's UID/GID 999. Moodle user files are on the HDD;
sessions, temporary processing, and caches are on NVMe. Install reviewed plugins
in the image and rebuild; web-based code/plugin deployment is disabled.

First startup initializes only a completely empty database. Credentials are passed
to the PHP installer in memory, not in process arguments. A nonempty partial
schema or a source/database version mismatch causes startup to stop with an
error. Existing databases are never automatically upgraded on reboot. The cron
container waits for the application, runs the official CLI cron every minute,
and reports unhealthy if the heartbeat stops.

The installer waits up to ten minutes for application health. A slow first Moodle
initialization may exceed that limit; this is reported as a failure even if the
container is still initializing. Inspect the application logs, wait for actual
completion, then rerun `sudo /srv/docker/start-all.sh moodle`. Do not delete the
database to work around a timeout. Compilation and image building happen before
the application health wait and can take additional time on a Pi.

To update Moodle source, first stop writes, create and verify a database/file
backup, and review the target version's upgrade requirements. Change the source
commit and local image tag together, build the new image, then explicitly run
the CLI upgrade as `www-data` in a one-off container before starting web/cron.
The host storage guard must pass first:

```bash
sudo /srv/docker/scripts/check-storage.sh
cd /srv/docker/compose/moodle
sudo docker compose stop app cron
# Back up now, using the documented backup procedure before modifying source.
sudo docker compose build --pull
sudo docker compose up -d db
sudo docker compose run --rm --no-deps --user 33:33 --entrypoint php app /var/www/moodle/admin/cli/upgrade.php --non-interactive
sudo /srv/docker/start-all.sh moodle
```

Do not perform a major-version upgrade by only changing PostgreSQL's image tag.
Restore the paired database and Moodle files/source if an upgrade needs rollback.

[Moodle 5.2 requirements](https://moodledev.io/general/releases/5.2),
[production installation and public web root](https://docs.moodle.org/502/en/Installation_Quickstart),
[MoodleHQ developer environment scope](https://github.com/moodlehq/moodle-docker),
[pinned Moodle source](https://github.com/moodle/moodle/tree/344232c15336c71b80f9aca8359ce0e0a9f3d116).

## Paperless-ngx

This package starts a **new** Paperless-ngx 3.2.1 database. It is not an in-place
v2 migration tool. Follow upstream migration instructions before attaching an
existing v2 library. PostgreSQL 17 meets the documented minimum of PostgreSQL 14.
Redis is on the private backend and requires a generated password. Only one OCR
task and one OCR thread run at a time. English OCR is configured; extra languages
can be configured through upstream settings. Tika/Gotenberg office conversion is
optional and is not added to this memory-constrained default stack.

The NVMe `data` folder contains the search index and application data. Original
and archived documents, import inbox, and exports stay on the HDD. Copying a file
to `consume` can cause it to be consumed and moved into Paperless's managed media
library; it is an import inbox, not an ordinary shared document folder.

[Paperless Docker setup](https://docs.paperless-ngx.com/setup/),
[settings](https://docs.paperless-ngx.com/configuration/),
[PostgreSQL requirements](https://docs.paperless-ngx.com/administration/),
[v3 migration](https://docs.paperless-ngx.com/migration-v3/).

## n8n

n8n and its external task runner use the same pinned 2.40.5 release. The runner
can reach only the task-broker network, cannot reach PostgreSQL, and has no host
mounts or internet egress. The main n8n service can reach external APIs. This
supports ordinary workflows without placing user Code node execution inside the
main credentials process. Reviewed runner configuration is needed for network
access or extra Python/JavaScript dependencies in Code nodes.

Preserve `N8N_ENCRYPTION_KEY` with every database backup: losing it can make saved
credentials unusable. Execution history is pruned after seven days and limited to
5000 records. The local HTTP bootstrap sets `N8N_SECURE_COOKIE=false`; after
configuring private HTTPS, set it to `true` and update protocol/editor/webhook URLs
in the Compose environment. The workflow and container timezone is Asia/Dubai.

[Official PostgreSQL Compose example](https://github.com/n8n-io/n8n-hosting/tree/main/docker-compose/withPostgres),
[external task runners](https://docs.n8n.io/deploy/host-n8n/configure-n8n/set-up-task-runners).

## Vaultwarden secure first login

Vaultwarden needs a browser secure context, so a normal HTTP LAN-IP page is not
a complete usable web-vault setup. A straightforward initial method is an SSH
tunnel from your client computer, substituting the actual Pi username/address:

```bash
ssh -N -L 8089:PI_ADDRESS:8089 pi5@PI_ADDRESS
```

Open `http://localhost:8089` in your client browser. Loopback is treated as a secure
context, and the SSH tunnel protects the connection. The default
`VAULTWARDEN_DOMAIN=http://localhost:8089` matches this bootstrap address.

For daily use, configure a private HTTPS endpoint such as Tailscale Serve, set
`VAULTWARDEN_DOMAIN` to that exact HTTPS origin, and restart the application.
No automatic public DNS or public certificate/router configuration is performed.
Visit `/admin` using the generated `ADMIN_TOKEN`, invite your email, then register
the invited address. SMTP is optional for an invitation created in `/admin`; if
configured, validate delivery before relying on mail-based recovery or alerts.

The random bearer admin token lives in a root-only `.env`. To store its Argon2 hash
instead, follow upstream `vaultwarden hash` instructions and Compose escaping
rules; do not replace it with a weak memorable value. Vaultwarden's own scheduled
job cron expressions use UTC internally even though container `TZ` is Asia/Dubai.

[Vaultwarden Compose and HTTPS](https://github.com/dani-garcia/vaultwarden/wiki/Using-Docker-Compose),
[PostgreSQL](https://github.com/dani-garcia/vaultwarden/wiki/Using-the-PostgreSQL-Backend),
[configuration including UTC schedules](https://github.com/dani-garcia/vaultwarden/blob/1.37.3/.env.template).

## Backup and verification

Use the layout-aware `portable-backup.sh` procedure in
`docs/PORTABLE-BACKUP.md`. It backs up registered selected data groups and paired
logical PostgreSQL dumps; it never copies a running database directory. Redis
caches/brokers, Gitea repositories, Wiki.js stored content, Vaultwarden attachments,
and n8n's key/config need inclusion alongside the database. Stop application writers
during a consistency-sensitive backup. For ONLYOFFICE, let active edits save and
close first; the original documents are stored by Nextcloud, not ONLYOFFICE.

Image names are exact version tags and no stack uses `latest`. Utility images are
digest-pinned; stateful images use the exact inspected version tags so their
database/application version pairing remains readable in Compose. The ARM64
registry manifest digests and source URLs were captured on **2026-09-22** in
`docs/STATEFUL-IMAGE-VERIFICATION.json`. Tags can be republished upstream; the Pi
installer must pull and inspect the architecture again. Moodle's local image is
built on the Pi and then inspected, not pulled from a nonexistent registry.

All eight stacks passed the standalone Docker Compose `config` parser, without
warnings, using dummy validation credentials. Static checks also passed for
ARM64 declarations, published host bindings, database isolation, resource limits,
mount directory declarations, and storage destinations. The Moodle entrypoint
passed `bash -n`. See `STATEFUL-CONFIG-VALIDATION.json`. PHP helpers and the custom
Moodle image still require execution/build verification on the Pi.

Validation performed during generation is recorded separately from runtime health.
The Pi must still pass database health, HTTP readiness, mount UUID checks, data
write/read checks, and the documented reboot procedure before this server can be
called fully installed and verified.
