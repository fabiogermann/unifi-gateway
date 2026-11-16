#!/usr/local/bin/python3
"""Generate /usr/local/etc/unifi-gateway/unifi-gateway.conf from config.xml.

Managed keys come from //OPNsense/unifigateway (the plugin settings model).
Runtime keys written by the daemon itself ([provisioned], is_adopted, key,
authkey-derived fields, dpi_*, speedtest_file, ...) are preserved verbatim:
the file is read, managed values are overwritten, everything else is kept.

Prints exactly OK on success (configd type:script convention).
"""
import configparser
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

CONFIG_XML = '/conf/config.xml'
TARGET = os.environ.get(
    'UNIFI_GW_CONFIG', '/usr/local/etc/unifi-gateway/unifi-gateway.conf')


def plugin_settings():
    try:
        root = ET.parse(CONFIG_XML).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f'ERROR: cannot read {CONFIG_XML}: {exc}', file=sys.stderr)
        sys.exit(1)
    node = root.find('.//OPNsense/unifigateway')
    if node is None:
        return {}
    out = {}
    for section in node:
        for field in section:
            out[f'{section.tag}.{field.tag}'] = (field.text or '').strip()
    return out


def ifconfig_value(ifname, kind):
    """kind: 'ether' -> MAC, 'inet' -> first IPv4 address."""
    try:
        out = subprocess.run(
            ['ifconfig', ifname], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        line = line.strip()
        if kind == 'ether' and line.startswith('ether '):
            return line.split()[1]
        if kind == 'inet' and line.startswith('inet '):
            return line.split()[1]
    return None


def main():
    s = plugin_settings()
    cfg = configparser.RawConfigParser()
    if os.path.exists(TARGET):
        cfg.read(TARGET)
    for section in ('global', 'gateway', 'provisioned'):
        if not cfg.has_section(section):
            cfg.add_section(section)

    controller = s.get('general.controller', '')
    port = s.get('general.controller_port', '') or '8080'
    if controller:
        cfg.set('gateway', 'url', f'http://{controller}:{port}/inform')

    hostname = s.get('general.hostname', '')
    if hostname:
        cfg.set('gateway', 'hostname', hostname)

    firmware = s.get('advanced.firmware', '')
    if firmware:
        cfg.set('gateway', 'firmware', firmware)

    log_level = s.get('advanced.log_level', '')
    if log_level:
        cfg.set('global', 'log level', log_level)

    wan_if = s.get('network.wan_if', '')
    lan_if = s.get('network.lan_if', '')
    if wan_if or lan_if:
        ports = []
        if wan_if:
            ports.append({'ifname': 'eth0', 'name': 'WAN', 'type': 'wan',
                          'realif': wan_if})
        if lan_if:
            ports.append({'ifname': 'eth1', 'name': 'LAN', 'type': 'lan',
                          'realif': lan_if})
        cfg.set('gateway', 'ports', json.dumps(ports))
        if lan_if:
            lan_ip = s.get('network.lan_ip', '') or ifconfig_value(lan_if, 'inet')
            lan_mac = ifconfig_value(lan_if, 'ether')
            if lan_ip:
                cfg.set('gateway', 'lan_ip', lan_ip)
            if lan_mac:
                cfg.set('gateway', 'lan_mac', lan_mac)
    else:
        lan_ip = s.get('network.lan_ip', '')
        if lan_ip:
            cfg.set('gateway', 'lan_ip', lan_ip)

    # Sensible defaults for keys the daemon needs; never downgrade existing.
    for section, key, value in (
        ('global', 'disable_broadcast', 'True'),
        ('gateway', 'device', 'UGW3'),
        ('gateway', 'device_display', 'UniFi-Gateway-3'),
        ('gateway', 'dhcp_lease_format', 'kea'),
        ('gateway', 'firmware', '4.4.57.5578372'),
    ):
        if not cfg.has_option(section, key):
            cfg.set(section, key, value)

    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    with open(TARGET, 'w') as fh:
        cfg.write(fh)
    print('OK')


if __name__ == '__main__':
    main()
