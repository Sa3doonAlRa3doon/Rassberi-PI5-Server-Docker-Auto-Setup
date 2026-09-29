#!/usr/bin/env python3
"""Watch mutable source tags rather than the package's immutable running digests."""
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, unquote

BASE = Path('/srv/docker')
sys.path.insert(0, str(BASE/'scripts'))


def source_tag(item):
    explicit = item.get('source_tag') or item.get('requested')
    if explicit and '@' not in explicit:
        return explicit
    text = item.get('evidence', '')
    match = re.search(r'[Ss]ource tag:?\s+([^\s;]+)', text)
    if match:
        return match[1].rstrip('.')
    source = urlsplit(item.get('source', ''))
    match = re.fullmatch(r'/v2/(.+)/manifests/([^/]+)', source.path)
    if match and not match[2].startswith('sha256:'):
        host = 'docker.io' if source.netloc == 'registry-1.docker.io' else source.netloc
        return host + '/' + match[1] + ':' + unquote(match[2])
    return None


def make_images(manifest):
    items = {}
    for app in manifest:
        for record in app.get('images', []):
            tag = source_tag(record)
            if not tag or '@' in tag:
                continue
            items.setdefault(tag, {'name':tag,'platform':{'os':'linux','arch':'arm64'},'metadata':{'application':app['name']}})
    return list(items.values())


def main():
    import storage_guard
    from monitoring_devices import atomic_json
    storage_guard.check(required=['root'])
    rows = make_images(json.loads((BASE/'manifest.json').read_text(encoding='utf-8')))
    if not rows:
        raise RuntimeError('No upstream source tags found; refusing an empty image watch list')
    atomic_json(BASE/'configs/diun/images.yml', rows)
    print(f'Diun watches {len(rows)} upstream source tags. Pinned runtime digests remain unchanged.')


if __name__ == '__main__':
    main()
