#!/usr/local/bin/python3
"""Print adoption state as one JSON object (for the plugin's status API)."""
import configparser
import json
import os
import xml.etree.ElementTree as ET

CONFIG_XML = '/conf/config.xml'
CONFIG = os.environ.get(
    'UNIFI_GW_CONFIG', '/usr/local/etc/unifi-gateway/unifi-gateway.conf')


def main():
    cfg = configparser.RawConfigParser()
    cfg.read(CONFIG)

    try:
        adopted = cfg.getboolean('gateway', 'is_adopted')
    except (configparser.Error, ValueError):
        adopted = False
    has_key = (cfg.has_option('provisioned', 'key')
               or cfg.has_option('gateway', 'key'))
    url = (cfg.get('gateway', 'url', fallback='') or '').strip()
    hostname = (cfg.get('gateway', 'hostname', fallback='') or '').strip()

    controller = ''
    if url.startswith('http'):
        controller = url.split('://', 1)[1].split('/')[0]

    if not hostname:
        try:
            root = ET.parse(CONFIG_XML).getroot()
            hostname = (root.findtext('.//system/hostname') or '').strip()
        except (OSError, ET.ParseError):
            pass

    print(json.dumps({
        'adopted': bool(adopted and has_key),
        'controller': controller,
        'hostname': hostname,
        'config': CONFIG,
    }))


if __name__ == '__main__':
    main()
