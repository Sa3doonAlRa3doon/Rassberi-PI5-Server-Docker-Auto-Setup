#!/usr/bin/env python3
"""Apply generated authentication using the upstream salted-password format."""
import base64
import hashlib
import os


def encode_password(password, salt):
    if not password or len(salt) != 32:
        raise ValueError('A password and 32-byte salt are required')
    return base64.b64encode(salt + hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)).decode('ascii')


def main():
    password = os.environ.pop('CHANGEDETECTION_PASSWORD', '')
    if not password or password == 'GENERATE':
        raise SystemExit('Run the Pi installer to generate CHANGEDETECTION_PASSWORD before starting.')
    os.environ['SALTED_PASS'] = encode_password(password, os.urandom(32))
    os.execv('/docker-entrypoint.sh', ['/docker-entrypoint.sh', 'python', '/app/changedetection.py', '-d', '/datastore'])


if __name__ == '__main__':
    main()
