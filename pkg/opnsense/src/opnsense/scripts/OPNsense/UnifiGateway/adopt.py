#!/usr/local/bin/python3
"""Run the UniFi adoption handshake (inform/enroll) for the emulator.

Phase 1 sends the initial inform; the controller lists the device as pending
(and answers 404). A human clicks Adopt in the controller UI; re-running the
same command then completes the exchange (setparam -> authkey stored). This
script wraps that flow: it fires phase 1, then polls by re-invoking until the
config shows adopted, a human-clickable window of up to 90 seconds.

Refuses to run when already adopted. Prints progress lines for the UI.
"""
import configparser
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

CONFIG_XML = '/conf/config.xml'
BINARY = '/usr/local/sbin/unifi-gateway'
CONFIG = os.environ.get(
    'UNIFI_GW_CONFIG', '/usr/local/etc/unifi-gateway/unifi-gateway.conf')
TIMEOUT = 90
INTERVAL = 5


def is_adopted():
    cfg = configparser.RawConfigParser()
    cfg.read(CONFIG)
    try:
        adopted = cfg.getboolean('gateway', 'is_adopted')
    except (configparser.Error, ValueError):
        adopted = False
    has_key = (cfg.has_option('provisioned', 'key')
               or cfg.has_option('gateway', 'key'))
    return bool(adopted and has_key)


def controller_url():
    root = ET.parse(CONFIG_XML).getroot()
    node = root.find('.//OPNsense/unifigateway/general')
    if node is None:
        return None
    host = (node.findtext('controller') or '').strip()
    port = (node.findtext('controller_port') or '8080').strip() or '8080'
    if not host:
        return None
    return f'http://{host}:{port}/inform'


def run_set_adopt(url):
    env = dict(os.environ)
    env['UNIFI_GW_CONFIG'] = CONFIG
    return subprocess.run(
        [BINARY, 'set-adopt', '-s', url],
        capture_output=True, text=True, timeout=40, env=env,
    )


def main():
    if is_adopted():
        print('Device is already adopted; nothing to do.')
        return 0

    url = controller_url()
    if not url:
        print('ERROR: no controller hostname configured. '
              'Set it under General Settings first.')
        return 1

    print(f'Contacting controller at {url} ...')
    try:
        proc = run_set_adopt(url)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f'ERROR: set-adopt failed to run: {exc}')
        return 1

    if is_adopted():
        print('Adoption completed.')
        return 0

    print('Device should now be listed as pending in the controller.')
    print(f'Click Adopt in the UniFi UI — waiting up to {TIMEOUT}s ...')
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        time.sleep(INTERVAL)
        try:
            proc = run_set_adopt(url)
        except (OSError, subprocess.SubprocessError):
            continue
        if is_adopted():
            print('Adoption completed.')
            return 0

    tail = (proc.stderr or proc.stdout or '').strip().splitlines()
    print('Timed out waiting for adoption.')
    if tail:
        print('Last daemon output: ' + tail[-1])
    print('Click Adopt in the controller UI and press the button again.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
