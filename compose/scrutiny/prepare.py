#!/usr/bin/env python3
import sys
sys.path.insert(0, '/srv/docker/scripts')
from monitoring_devices import configure

if __name__ == '__main__':
    configure('scrutiny')
