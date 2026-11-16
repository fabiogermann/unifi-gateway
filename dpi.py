# -*- coding: utf-8 -*-
"""DPI (traffic identification) section synthesis for the inform payload.

A real UGW3 reports deep-packet-inspection data in the inform JSON:

- ``has_dpi: true``                  — capability flag
- ``dpi_version: "<major>.<minor>"`` — TDTS signature db version (e.g. "1.404")
- ``dpi-stats`` / ``dpi-stats-table`` / ``dpi-clients`` — per-app and
  per-client counters (rx_bytes/rx_packets/tx_bytes/tx_packets), keyed by
  TDTS application/category ids (the controller renders names from its own
  copy of the database, so ids must match, not names).

The exact row nesting is being probed against live controllers; this module
deliberately passes section content through verbatim so the wire shape can be
iterated from the stub file without code changes.

Sources:
- ``StaticStubSource``: rows from a JSON file (wire-shape probing, offline
  captures from a real USG).
- (future) ZenarmorSource: live app counters from Zenarmor on OPNsense,
  mapped to TDTS app ids.
"""
import json
import logging
import os

logger = logging.getLogger('unifi-gateway')

DPI_SECTION_KEYS = ('dpi-stats', 'dpi-stats-table', 'dpi-clients')

DEFAULT_DPI_VERSION = '1.404'


class StaticStubSource:
    """Yields DPI sections verbatim from a JSON file.

    File shape::

        {
          "dpi_version": "1.404",            # optional, overrides config
          "dpi-stats": [...],                # optional, passed through as-is
          "dpi-stats-table": [...],
          "dpi-clients": [...]
        }
    """

    def __init__(self, path):
        self.path = path

    def read(self):
        with open(self.path) as fh:
            return json.load(fh)


def _resolve_stub_path(config, stub_path):
    if os.path.isabs(stub_path):
        return stub_path
    base = os.path.dirname(
        os.environ.get('UNIFI_GW_CONFIG', 'conf/unifi-gateway.conf'))
    return os.path.join(base, stub_path)


def dpi_sections(config):
    """Return the DPI-related inform payload keys for this device.

    Empty dict when DPI is disabled (default) — payload stays identical to
    upstream behaviour.
    """
    if not config.has_option('gateway', 'has_dpi'):
        return {}
    try:
        if not config.getboolean('gateway', 'has_dpi'):
            return {}
    except ValueError:
        logger.warning('has_dpi is not a boolean: %r — ignoring',
                       config.get('gateway', 'has_dpi'))
        return {}

    sections = {
        'has_dpi': True,
        'dpi_version': config.get('gateway', 'dpi_version',
                                  fallback=DEFAULT_DPI_VERSION),
    }

    if not config.has_option('gateway', 'dpi_stub_file'):
        return sections

    stub_path = _resolve_stub_path(
        config, config.get('gateway', 'dpi_stub_file'))
    try:
        stub = StaticStubSource(stub_path).read()
    except Exception as e:
        logger.warning('DPI stub %s unreadable: %s', stub_path, e)
        return sections

    if 'dpi_version' in stub:
        sections['dpi_version'] = stub['dpi_version']
    for key in DPI_SECTION_KEYS:
        if key in stub:
            sections[key] = stub[key]
    return sections
