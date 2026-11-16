# -*- coding: utf-8 -*-
"""Tests for DPI section synthesis (dpi.py) and its inform-payload wiring."""
import configparser
import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dpi import dpi_sections, DEFAULT_DPI_VERSION  # noqa: E402
import unifi_protocol  # noqa: E402


def _cfg(gateway=None):
    cfg = configparser.ConfigParser()
    cfg.add_section('gateway')
    for k, v in (gateway or {}).items():
        cfg.set('gateway', k, v)
    return cfg


class TestDpiSections:
    def test_absent_option_returns_empty(self):
        assert dpi_sections(_cfg()) == {}

    def test_disabled_returns_empty(self):
        assert dpi_sections(_cfg({'has_dpi': 'False'})) == {}

    def test_non_boolean_warns_and_returns_empty(self, caplog):
        with caplog.at_level('WARNING', logger='unifi-gateway'):
            assert dpi_sections(_cfg({'has_dpi': 'banana'})) == {}
        assert 'has_dpi' in caplog.text

    def test_flags_only_without_stub(self):
        out = dpi_sections(_cfg({'has_dpi': 'True'}))
        assert out == {'has_dpi': True, 'dpi_version': DEFAULT_DPI_VERSION}

    def test_config_dpi_version(self):
        out = dpi_sections(_cfg({'has_dpi': 'yes', 'dpi_version': '9.9'}))
        assert out['dpi_version'] == '9.9'

    def test_stub_sections_pass_through_verbatim(self, tmp_path):
        rows = [{'app': 2000, 'cat': 141, 'rx_bytes': 5, 'tx_bytes': 7}]
        stub = tmp_path / 'stub.json'
        stub.write_text(json.dumps({
            'dpi_version': '1.999',
            'dpi-stats-table': rows,
            'dpi-clients': [],
        }))
        out = dpi_sections(_cfg({
            'has_dpi': 'True',
            'dpi_stub_file': str(stub),
        }))
        assert out['has_dpi'] is True
        assert out['dpi_version'] == '1.999'  # stub overrides config
        assert out['dpi-stats-table'] == rows
        assert out['dpi-clients'] == []
        assert 'dpi-stats' not in out

    def test_relative_stub_resolves_against_config_dir(self, tmp_path, monkeypatch):
        conf_dir = tmp_path / 'conf'
        conf_dir.mkdir()
        (conf_dir / 'stub.json').write_text('{"dpi-stats-table": []}')
        monkeypatch.setenv('UNIFI_GW_CONFIG', str(conf_dir / 'unifi-gateway.conf'))
        out = dpi_sections(_cfg({
            'has_dpi': 'True',
            'dpi_stub_file': 'stub.json',
        }))
        assert out['dpi-stats-table'] == []

    def test_unreadable_stub_keeps_flags_only(self, tmp_path, caplog):
        with caplog.at_level('WARNING', logger='unifi-gateway'):
            out = dpi_sections(_cfg({
                'has_dpi': 'True',
                'dpi_stub_file': str(tmp_path / 'missing.json'),
            }))
        assert 'dpi-stats-table' not in out
        assert out['has_dpi'] is True


class _FakeDC:
    """Minimal datacollector stand-in for _create_complete_inform."""
    data = {'macs': {}, 'ip': {}, 'system_stats': {'cpu': '1', 'mem': '2'},
            'dhcp_leases': [], 'speedtest': {}}


def _inform_cfg(tmp_path, extra=None):
    cfg = configparser.ConfigParser()
    cfg.read_dict({
        'gateway': {
            'ports': '[{"ifname":"eth0","name":"WAN","type":"wan","realif":"vmx0"},'
                     '{"ifname":"eth1","name":"LAN","type":"lan","realif":"vmx1"}]',
            'is_adopted': 'True',
            'firmware': '4.4.57.5578372',
            'device': 'UGW3',
            'device_display': 'UniFi-Gateway-3',
            'lan_ip': '192.168.1.1',
            'lan_mac': 'bc:24:11:8d:dd:50',
            'url': 'http://controller:8080/inform',
        },
        'provisioned': {},
    })
    for k, v in (extra or {}).items():
        cfg.set('gateway', k, v)
    return cfg


class TestCompleteInformIntegration:
    def _build(self, cfg):
        with patch.object(unifi_protocol, 'get_if_table', return_value=[]), \
             patch.object(unifi_protocol, 'get_network_table', return_value=[]):
            return json.loads(
                unifi_protocol._create_complete_inform(cfg, _FakeDC()))

    def test_dpi_keys_absent_by_default(self, tmp_path):
        payload = self._build(_inform_cfg(tmp_path))
        assert 'has_dpi' not in payload or payload['has_dpi'] is False
        assert 'dpi_version' not in payload
        assert 'dpi-stats-table' not in payload

    def test_dpi_keys_present_when_enabled(self, tmp_path):
        stub = tmp_path / 'stub.json'
        stub.write_text(json.dumps({'dpi-stats-table': [{'app': 1}]}))
        cfg = _inform_cfg(tmp_path, {
            'has_dpi': 'True',
            'dpi_stub_file': str(stub),
        })
        payload = self._build(cfg)
        assert payload['has_dpi'] is True
        assert payload['dpi_version'] == DEFAULT_DPI_VERSION
        assert payload['dpi-stats-table'] == [{'app': 1}]
        # upstream payload must be intact too
        assert payload['model'] == 'UGW3'
        assert 'if_table' in payload
