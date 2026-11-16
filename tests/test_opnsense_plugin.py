# -*- coding: utf-8 -*-
"""Tests for the os-unifi-gateway OPNsense plugin package.

Stdlib-only: builds the pkg (UI-only, --no-binary) in-process and checks the
pkg-ng wire format plus the plugin tree's structural contracts (XML validity,
required actions, model field types).
"""
import configparser
import importlib.util
import json
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
PLUGIN = REPO / 'pkg' / 'opnsense'
SRC = PLUGIN / 'src'

_spec = importlib.util.spec_from_file_location(
    'build_pkg_opnsense', PLUGIN / 'scripts' / 'build_pkg_opnsense.py')
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

VALID_FIELD_TYPES = {
    'BooleanField', 'TextField', 'StrictTextField', 'PortField',
    'OptionField', 'IntegerField', 'UrlField', 'NetworkField',
    'DescriptionField', 'ArrayField', 'HostnameField',
}


@pytest.fixture(scope='module')
def pkg_path(tmp_path_factory):
    out = tmp_path_factory.mktemp('pkg') / 'os-unifi-gateway-test.pkg'
    builder.build('0.0.0-test', 1, out, sbin=None)
    return out


class TestPluginPkg:
    def test_wire_format(self, pkg_path):
        assert builder.verify(pkg_path)

    def test_manifest(self, pkg_path):
        with tarfile.open(str(pkg_path), 'r:*') as tar:
            members = tar.getmembers()
            assert members[0].name.lstrip('./') == '+COMPACT_MANIFEST'
            assert members[1].name.lstrip('./') == '+MANIFEST'
            mf = json.loads(tar.extractfile('+MANIFEST').read())
        assert mf['name'] == 'os-unifi-gateway'
        assert mf['abi'] == 'FreeBSD:15:amd64'
        assert mf['arch'] == 'freebsd:15:x86:64'
        assert 'post-install' in mf['scripts']

    def test_required_files(self, pkg_path):
        with tarfile.open(str(pkg_path), 'r:*') as tar:
            names = set(tar.getnames())
        required = {
            '/usr/local/etc/rc.d/unifi_gateway',
            '/usr/local/etc/inc/plugins.inc.d/unifigateway.inc',
            '/usr/local/etc/unifi-gateway/unifi-gateway.sample.conf',
            '/usr/local/opnsense/service/conf/actions.d/actions_unifigateway.conf',
            '/usr/local/opnsense/mvc/app/models/OPNsense/UnifiGateway/UnifiGateway.xml',
            '/usr/local/opnsense/mvc/app/models/OPNsense/UnifiGateway/UnifiGateway.php',
            '/usr/local/opnsense/mvc/app/models/OPNsense/UnifiGateway/Menu/Menu.xml',
            '/usr/local/opnsense/mvc/app/models/OPNsense/UnifiGateway/ACL/ACL.xml',
            '/usr/local/opnsense/mvc/app/controllers/OPNsense/UnifiGateway/IndexController.php',
            '/usr/local/opnsense/mvc/app/controllers/OPNsense/UnifiGateway/Api/ServiceController.php',
            '/usr/local/opnsense/mvc/app/controllers/OPNsense/UnifiGateway/Api/SettingsController.php',
            '/usr/local/opnsense/mvc/app/controllers/OPNsense/UnifiGateway/Api/AdoptController.php',
            '/usr/local/opnsense/mvc/app/views/OPNsense/UnifiGateway/index.volt',
            '/usr/local/opnsense/scripts/OPNsense/UnifiGateway/generate_config.py',
            '/usr/local/opnsense/scripts/OPNsense/UnifiGateway/adopt.py',
            '/usr/local/opnsense/scripts/OPNsense/UnifiGateway/adoption_status.py',
        }
        assert required <= names, required - names

    def test_exec_modes(self, pkg_path):
        with tarfile.open(str(pkg_path), 'r:*') as tar:
            for m in tar.getmembers():
                if m.name.endswith(('.py', '.sh')) or '/rc.d/' in m.name:
                    assert m.mode & 0o111, f'{m.name} not executable'

    def test_binary_overlay(self, tmp_path):
        fake = tmp_path / 'fake-binary'
        fake.write_bytes(b'\x7fELF-fake')
        out = tmp_path / 'with-bin.pkg'
        builder.build('0.0.0-test', 1, out, sbin=fake)
        with tarfile.open(str(out), 'r:*') as tar:
            m = tar.getmember('/usr/local/sbin/unifi-gateway')
            assert m.mode & 0o111
            assert tar.extractfile(m).read() == b'\x7fELF-fake'
        assert builder.verify(out)

    def test_requires_binary_unless_flagged(self, tmp_path):
        # main() must exit when neither --sbin nor --no-binary is given
        import sys
        argv = sys.argv
        try:
            sys.argv = ['build', '--version', '1', '--out', str(tmp_path / 'x.pkg')]
            with pytest.raises(SystemExit):
                builder.main()
        finally:
            sys.argv = argv


class TestPluginStructure:
    def test_xml_files_well_formed(self):
        for xml in SRC.rglob('*.xml'):
            ET.parse(str(xml)), xml

    def test_model_field_types_valid(self):
        root = ET.parse(str(
            SRC / 'opnsense/mvc/app/models/OPNsense/UnifiGateway/UnifiGateway.xml'
        )).getroot()
        assert root.find('mount').text == '//OPNsense/unifigateway'
        for el in root.iter():
            ftype = el.get('type')
            if ftype and not ftype.startswith('.'):
                assert ftype in VALID_FIELD_TYPES, f'{el.tag}: {ftype}'

    def test_actions_cover_service_and_adopt(self):
        text = (SRC / 'opnsense/service/conf/actions.d/actions_unifigateway.conf'
                ).read_text()
        cp = configparser.ConfigParser(allow_no_value=True)
        cp.read_string(text)
        for section in ('start', 'stop', 'restart', 'status',
                        'generate-config', 'adopt', 'adoption-status'):
            assert cp.has_section(section), section
        assert 'exit 0' in cp.get('status', 'command')

    def test_menu_and_acl_reference_module(self):
        menu = (SRC / 'opnsense/mvc/app/models/OPNsense/UnifiGateway/Menu/Menu.xml'
                ).read_text()
        assert '/ui/unifigateway/' in menu and 'UnifiGateway' in menu
        acl = (SRC / 'opnsense/mvc/app/models/OPNsense/UnifiGateway/ACL/ACL.xml'
               ).read_text()
        assert 'ui/unifigateway/*' in acl and 'api/unifigateway/*' in acl

    def test_sample_conf_parses_as_ini(self):
        text = (SRC / 'etc/unifi-gateway/unifi-gateway.sample.conf').read_text()
        cp = configparser.RawConfigParser()
        cp.read_string(text)
        assert cp.has_section('gateway') and cp.has_section('provisioned')
