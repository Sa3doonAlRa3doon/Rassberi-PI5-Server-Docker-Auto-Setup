#!/usr/bin/env python3
"""Minimal Docker API gateway: only opted-in, running NVMe workloads can heal."""
import http.client
import json
import os
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

LABEL = 'pi.autoheal.nvme'
SOCKET = '/var/run/docker.sock'
MOUNTINFO = '/host/mountinfo'
ID = r'[a-f0-9]{64}'


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__('localhost', timeout=45)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


def docker(method, path):
    client = UnixHTTPConnection()
    try:
        client.request(method, path, body=b'' if method == 'POST' else None)
        response = client.getresponse()
        return response.status, response.getheader('Content-Type', 'application/json'), response.read()
    finally:
        client.close()


def mount_devices(text):
    rows = []
    for line in text.splitlines():
        columns = line.split()
        if len(columns) < 10:
            continue
        path = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), columns[4])
        rows.append((path, columns[2]))
    root = next((device for path, device in rows if path == '/'), None)
    if not root:
        raise ValueError('Host root mount identity is unavailable')
    return root, sorted(rows, key=lambda x: len(x[0]), reverse=True)


def eligible(container, mount_text):
    labels = container.get('Config', {}).get('Labels') or {}
    host = container.get('HostConfig') or {}
    if labels.get(LABEL) != 'true' or not labels.get('com.docker.compose.project', '').startswith('pi-'):
        return False
    if labels.get('com.docker.compose.project') in {'pi-autoheal', 'pi-docker-socket-proxy'}:
        return False
    if container.get('State', {}).get('Status') != 'running':
        return False
    if host.get('Privileged') or host.get('Devices') or host.get('DeviceRequests'):
        return False
    root, mounts = mount_devices(mount_text)
    for item in container.get('Mounts') or []:
        if item.get('Type') == 'tmpfs':
            continue
        if item.get('Type') != 'bind':
            return False
        source = item.get('Source', '')
        if not item.get('RW') and source in {'/etc/localtime', '/etc/timezone'}:
            continue
        if not source.startswith(('/srv/docker/', '/var/lib/docker/', '/var/lib/containerd/')):
            return False
        device = next((dev for path, dev in mounts if source == path or source.startswith(path.rstrip('/') + '/')), None)
        if device != root:
            return False
    return True


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        # Avoid logging container inspect responses or query arguments.
        print('%s %s' % (self.command, urlsplit(self.path).path), flush=True)

    def reply(self, status, data, content_type='application/json'):
        if not isinstance(data, bytes):
            data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Connection', 'close')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)
        self.close_connection = True

    def handle_api(self):
        parts = urlsplit(self.path)
        path = re.sub(r'^/v[0-9]+\.[0-9]+', '', parts.path)
        if parts.scheme or parts.netloc or '%' in parts.path or '..' in path:
            return self.reply(403, {'message': 'Invalid API path'})
        if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Length', '0') != '0':
            return self.reply(403, {'message': 'Request bodies are not accepted'})
        try:
            if self.command in {'GET', 'HEAD'} and path in {'/_ping', '/version'}:
                code, kind, data = docker(self.command, self.path)
                return self.reply(code, data, kind)
            if self.command == 'GET' and path == '/containers/json':
                code, kind, data = docker('GET', self.path)
                if code != 200:
                    return self.reply(code, data, kind)
                with open(MOUNTINFO, encoding='utf-8') as stream:
                    mounts = stream.read()
                safe = []
                for row in json.loads(data):
                    identifier = row.get('Id', '')
                    if not re.fullmatch(ID, identifier):
                        continue
                    status, _, inspected = docker('GET', '/containers/' + identifier + '/json')
                    if status == 200 and eligible(json.loads(inspected), mounts):
                        safe.append(row)
                return self.reply(200, safe)
            match = re.fullmatch(r'/containers/(' + ID + r')/(json|restart|stop)', path)
            if not match:
                return self.reply(403, {'message': 'API endpoint is not permitted'})
            identifier, action = match.groups()
            if (action == 'json' and self.command != 'GET') or (action != 'json' and self.command != 'POST'):
                return self.reply(403, {'message': 'API method is not permitted'})
            code, kind, data = docker('GET', '/containers/' + identifier + '/json')
            if code != 200:
                return self.reply(code, data, kind)
            container = json.loads(data)
            with open(MOUNTINFO, encoding='utf-8') as stream:
                allowed = eligible(container, stream.read())
            if not allowed:
                return self.reply(403, {'message': 'Container is outside the running NVMe-only opt-in policy'})
            if action == 'json':
                return self.reply(code, data, kind)
            if action == 'restart' and container.get('State', {}).get('Health', {}).get('Status') != 'unhealthy':
                return self.reply(409, {'message': 'Container is no longer unhealthy'})
            code, kind, data = docker('POST', self.path)
            return self.reply(code, data, kind)
        except (OSError, ValueError, http.client.HTTPException):
            return self.reply(503, {'message': 'Docker or mount identity verification unavailable; action refused'})

    do_GET = handle_api
    do_HEAD = handle_api
    do_POST = handle_api
    do_DELETE = handle_api
    do_PUT = handle_api
    do_PATCH = handle_api


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 2375), Handler).serve_forever()
