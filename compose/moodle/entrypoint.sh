#!/usr/bin/env bash
set -Eeuo pipefail
umask 0027

: "${MOODLE_DB_PASSWORD:?Missing database password}"
: "${MOODLE_WWWROOT:?Missing canonical site URL}"

# Mount directories are provisioned by the host installer after UUID checks.
# Do not recursively chown existing user data during every reboot.
for path in /var/moodledata /var/moodlecache; do
    if [[ ! -d "$path" || ! -w "$path" ]]; then
        printf 'Required persistent directory is unavailable: %s\n' "$path" >&2
        exit 1
    fi
done
runuser -u www-data -p -- mkdir -p \
    /var/moodlecache/cache /var/moodlecache/localcache /var/moodlecache/temp \
    /var/moodlecache/backuptemp /var/moodlecache/sessions

if [[ "${1:-web}" == cron ]]; then
    trap 'exit 0' TERM INT
    while true; do
        runuser -u www-data -p -- php /usr/local/bin/moodle-health.php
        runuser -u www-data -p -- php /var/www/moodle/admin/cli/cron.php
        touch /tmp/moodle-cron-ok
        sleep 60 &
        wait "$!"
    done
fi

state=$(php /usr/local/bin/moodle-db-state.php)
case "$state" in
    empty)
        : "${MOODLE_ADMIN_PASSWORD:?Missing initial administrator password}"
        printf 'Initializing a new empty Moodle database.\n'
        runuser -u www-data -p -- php /usr/local/bin/moodle-install.php
        ;;
    ready)
        printf 'Existing Moodle database matches the installed source version.\n'
        ;;
    *)
        printf 'Moodle database needs manual inspection or an explicit upgrade (%s). No changes were made.\n' "$state" >&2
        exit 1
        ;;
esac
exec docker-php-entrypoint apache2-foreground
