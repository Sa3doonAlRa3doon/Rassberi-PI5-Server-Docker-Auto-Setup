#!/bin/sh
set -eu
umask 077
log=/data/notifications.log
if [ -f "$log" ] && [ "$(wc -c < "$log")" -gt 1048576 ]; then mv -f "$log" "$log.1"; fi
printf '%s | %s | %s | %s\n' "$(date -u +%FT%TZ)" "${DIUN_ENTRY_STATUS:-unknown}" "${DIUN_ENTRY_IMAGE:-unknown}" "${DIUN_ENTRY_DIGEST:-unknown}" >> "$log"
printf 'IMAGE UPDATE: %s %s\n' "${DIUN_ENTRY_STATUS:-unknown}" "${DIUN_ENTRY_IMAGE:-unknown}"
