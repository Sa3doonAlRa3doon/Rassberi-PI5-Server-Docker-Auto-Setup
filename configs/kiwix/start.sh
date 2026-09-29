#!/bin/sh
set -eu
# POSIX shell globbing safely preserves filenames containing spaces.
set -- /data/*.zim
if [ -f "$1" ]; then
    exec /usr/local/bin/kiwix-serve --port=8080 "$@"
fi
printf '%s\n' 'WARNING: Kiwix has no ZIM archives yet; serving an empty library.'
exec /usr/local/bin/kiwix-serve --port=8080 --library /config/empty-library.xml
