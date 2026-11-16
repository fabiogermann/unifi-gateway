# -*- coding: utf-8 -*-
"""Fail-closed tests for ci/upload-ak.sh against a mock AK+Cloudflare edge.

Stdlib-only so it runs anywhere (no psutil/Crypto needed). Pins the CI
contract: only HTTP 201 may pass — an SSO HTML page (200), a banned-client
403/1010, or a backend 401 must all fail the upload.
"""
import hashlib
import http.server
import json
import os
import subprocess
import threading

import pytest

REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
SCRIPT = os.path.join(REPO_ROOT, 'ci', 'upload-ak.sh')

GOOD_CF_ID = 'cf-id-123.access'
GOOD_CF_SECRET = 'cf-secret-abc'
GOOD_TOKEN = 'ak-write-token-xyz'


class _MockAK(http.server.BaseHTTPRequestHandler):
    mode = 'happy'          # happy | sso | banned | badtoken
    last_request = None

    def log_message(self, *a):
        pass

    def do_PUT(self):
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length)
        type(self).last_request = {
            'path': self.path,
            'cf_id': self.headers.get('CF-Access-Client-Id'),
            'cf_secret': self.headers.get('CF-Access-Client-Secret'),
            'auth': self.headers.get('Authorization'),
            'checksum': self.headers.get('X-Checksum-SHA256'),
            'ua': self.headers.get('User-Agent'),
            'body': body,
        }
        if self.mode == 'sso':
            return self._reply(200, '<html><title>Sign in</title></html>',
                               'text/html')
        if self.mode == 'banned':
            return self._reply(403, 'error code: 1010', 'text/plain')
        if self.headers.get('CF-Access-Client-Id') != GOOD_CF_ID or \
                self.headers.get('CF-Access-Client-Secret') != GOOD_CF_SECRET:
            return self._reply(403, 'error code: 1010', 'text/plain')
        if self.mode == 'badtoken' or \
                self.headers.get('Authorization') != f'Bearer {GOOD_TOKEN}':
            return self._reply(401, json.dumps({'error': 'no API key'}),
                               'application/json')
        self._reply(201, json.dumps({'status': 'created'}), 'application/json')

    def _reply(self, code, body, ctype):
        data = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def server():
    srv = http.server.HTTPServer(('127.0.0.1', 0), _MockAK)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()


@pytest.fixture
def pkg_file(tmp_path):
    f = tmp_path / 'unifi-gateway-0.0.0.pkg'
    f.write_bytes(b'fake-pkg-bytes' * 100)
    return f


def _env(srv, **overrides):
    env = {
        'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
        'AK_URL': f'http://127.0.0.1:{srv.server_port}',
        'AK_API_TOKEN': GOOD_TOKEN,
        'AK_CF_ACCESS_CLIENT_ID': GOOD_CF_ID,
        'AK_CF_ACCESS_CLIENT_SECRET': GOOD_CF_SECRET,
    }
    for k, v in overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return env


def _run(srv, pkg_file, env):
    return subprocess.run(
        ['sh', SCRIPT, str(pkg_file), 'freebsd-pkg', 'FreeBSD:15:amd64'],
        env=env, capture_output=True, text=True, timeout=30)


class TestUploadAk:
    def test_happy_path_201(self, server, pkg_file):
        server.RequestHandlerClass.mode = 'happy'
        r = _run(server, pkg_file, _env(server))
        assert r.returncode == 0, r.stderr
        req = server.RequestHandlerClass.last_request
        assert req['path'].startswith(
            '/api/v1/repositories/freebsd-pkg/artifacts/FreeBSD%3A15%3Aamd64/')
        assert req['path'].endswith('/unifi-gateway-0.0.0.pkg')
        assert req['checksum'] == hashlib.sha256(pkg_file.read_bytes()).hexdigest()
        assert req['auth'] == f'Bearer {GOOD_TOKEN}'
        assert req['cf_id'] == GOOD_CF_ID
        assert 'unifi-gateway-ci' in req['ua']

    def test_sso_html_200_fails_closed(self, server, pkg_file):
        """A Cloudflare SSO login page (HTTP 200 text/html) must FAIL."""
        server.RequestHandlerClass.mode = 'sso'
        r = _run(server, pkg_file, _env(server))
        assert r.returncode != 0

    def test_banned_client_403_fails(self, server, pkg_file):
        server.RequestHandlerClass.mode = 'banned'
        r = _run(server, pkg_file, _env(server))
        assert r.returncode != 0
        assert '1010' in r.stderr

    def test_backend_401_fails(self, server, pkg_file):
        server.RequestHandlerClass.mode = 'badtoken'
        r = _run(server, pkg_file, _env(server))
        assert r.returncode != 0

    def test_wrong_cf_headers_rejected_by_edge(self, server, pkg_file):
        server.RequestHandlerClass.mode = 'happy'
        r = _run(server, pkg_file,
                 _env(server, AK_CF_ACCESS_CLIENT_SECRET='wrong'))
        assert r.returncode != 0  # mock edge 403s -> script fails

    def test_missing_secret_guard_fails_before_curl(self, server, pkg_file):
        server.RequestHandlerClass.mode = 'happy'
        r = _run(server, pkg_file, _env(server, AK_API_TOKEN=None))
        assert r.returncode != 0
        assert 'AK_API_TOKEN' in r.stderr
