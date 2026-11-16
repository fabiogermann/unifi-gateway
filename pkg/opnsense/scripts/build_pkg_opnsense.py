#!/usr/bin/env python3
"""
build_pkg_opnsense.py — Build the os-unifi-gateway OPNsense plugin .pkg using
ONLY the Python standard library (lzma/xz). No zstandard, no GNU tar, no
pkg(8) — works on any CI host (the plugin is pure PHP/scripts plus the
PyInstaller daemon binary supplied via --sbin).

pkg-ng wire format (same as squid-icap-nblock's builder):
  - tar archive (xz-compressed) with +COMPACT_MANIFEST first, +MANIFEST second
  - member names are ABSOLUTE install paths (e.g. /usr/local/etc/...)
  - manifests are JSON (+MANIFEST carries per-file "1$sha256hex" + scripts)

Usage:
  python3 build_pkg_opnsense.py --version <x.y.z> --sbin <unifi-gateway-binary> \
      --out dist/os-unifi-gateway-<x.y.z>.pkg [--verify]
  --no-binary builds a UI-only package for development iterations (loudly).
"""

import argparse
import hashlib
import io
import json
import lzma
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).parent.parent          # pkg/opnsense/
SRC = HERE / "src"
PREFIX = "/usr/local"

PKG_NAME = "os-unifi-gateway"
MAINT = "fabiogermann@users.noreply.github.com"
WWW = "https://github.com/fabiogermann/unifi-gateway"
COMMENT = "UniFi Gateway Emulator for OPNsense"
DESC = ("Emulates a Ubiquiti UniFi Gateway (UGW3) to a UniFi controller: "
        "OPNsense appears as an adoptable USG-3P and reports interface, "
        "client and DPI telemetry. Provides the OPNsense UI for service "
        "control, controller inform/enroll configuration and adoption.")

POST_INSTALL = """#!/bin/sh
if [ ! -f /usr/local/etc/unifi-gateway/unifi-gateway.conf ]; then
    cp /usr/local/etc/unifi-gateway/unifi-gateway.sample.conf \\
        /usr/local/etc/unifi-gateway/unifi-gateway.conf
fi

# Register configd actions immediately
/usr/local/etc/rc.d/configd restart

# Generate the daemon config from config.xml when the plugin is configured
/usr/local/bin/python3 \\
    /usr/local/opnsense/scripts/OPNsense/UnifiGateway/generate_config.py \\
    >/dev/null 2>&1 || true

# Persist the service across reboots; preserve an admin override on upgrades
if ! /usr/sbin/sysrc -n unifi_gateway_enable >/dev/null 2>&1; then
    /usr/sbin/sysrc unifi_gateway_enable=YES
fi

# Refresh cached MVC classes and the merged menu immediately after install
/usr/local/bin/php \\
    /usr/local/opnsense/scripts/OPNsense/UnifiGateway/refresh_menu.php
/usr/local/etc/rc.d/php_fpm restart
"""
POST_DEINSTALL = """#!/bin/sh
exit 0
"""


def esc_script(s: str) -> str:
    out = []
    for ch in s:
        raw = ch.encode("utf-8")
        if len(raw) == 1 and raw[0] < 0x80:
            out.append(ch)
        else:
            out.extend("%%%02x" % b for b in raw)
    return "".join(out)


def sha256hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect_files(sbin: Path | None) -> dict:
    files = {}
    for p in sorted(SRC.rglob("*")):
        if not p.is_file():
            continue
        parts = p.parts
        if "__pycache__" in parts or ".pytest_cache" in parts or p.suffix == ".pyc":
            continue
        install = PREFIX + "/" + str(p.relative_to(SRC))
        files[install] = p
    if sbin is not None:
        files[PREFIX + "/sbin/unifi-gateway"] = sbin
    return files


def manifest_dict(version, revision, files) -> dict:
    hashes = {}
    flatsize = 0
    for install_path, src_path in sorted(files.items()):
        data = src_path.read_bytes()
        hashes[install_path] = "1$" + sha256hex(data)
        flatsize += len(data)

    base = {
        "name": PKG_NAME, "origin": f"opnsense/{PKG_NAME}",
        "version": version, "comment": COMMENT, "maintainer": MAINT,
        "www": WWW, "abi": "FreeBSD:15:amd64", "arch": "freebsd:15:x86:64",
        "prefix": PREFIX, "flatsize": flatsize,
        "licenselogic": "single", "licenses": ["MIT"], "desc": DESC,
        "categories": ["opnsense"],
        "annotations": {"plugin_php_requires": "0",
                        "plugin_revision": str(revision),
                        "repo_type": "binary"},
    }
    full = dict(base)
    full["files"] = hashes
    full["scripts"] = {"post-install": esc_script(POST_INSTALL),
                       "post-deinstall": esc_script(POST_DEINSTALL)}
    return full, base


EXEC_SUFFIXES = (".sh", ".py")


def is_exec(install_path: str) -> bool:
    return (install_path.endswith(EXEC_SUFFIXES)
            or "/rc.d/" in install_path
            or "/sbin/" in install_path
            or install_path.endswith("refresh_menu.php"))


def build(version: str, revision: int, out: Path, sbin: Path | None) -> dict:
    files = collect_files(sbin)
    if not files:
        sys.exit("ERROR: nothing under src/")
    full, compact = manifest_dict(version, revision, files)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, obj in (("+COMPACT_MANIFEST", compact), ("+MANIFEST", full)):
            data = json.dumps(obj, separators=(",", ":")).encode()
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode, ti.mtime = len(data), 0o644, int(time.time())
            tar.addfile(ti, io.BytesIO(data))
        for install_path, src_path in sorted(files.items()):
            data = src_path.read_bytes()
            ti = tarfile.TarInfo(install_path)  # absolute member name
            ti.size = len(data)
            ti.mode = 0o755 if is_exec(install_path) else 0o644
            ti.mtime = int(src_path.stat().st_mtime)
            tar.addfile(ti, io.BytesIO(data))

    compressed = lzma.compress(buf.getvalue(), preset=6)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(compressed)
    print(f"Built:    {out}")
    print(f"Files:    {len(files)}")
    print(f"Flatsize: {full['flatsize']:,} bytes")
    print(f"Pkg size: {len(compressed):,} bytes xz")
    return full


def verify(pkg: Path) -> bool:
    with tarfile.open(str(pkg), mode="r:*") as tar:
        ms = tar.getmembers()
        assert ms[0].name.lstrip("./") == "+COMPACT_MANIFEST"
        mf = json.loads(tar.extractfile("+MANIFEST").read())
        errors = 0
        for install_path, h in mf["files"].items():
            member = next((m for m in ms if m.name == install_path), None)
            if member is None:
                print(f"FAIL missing: {install_path}")
                errors += 1
                continue
            if "1$" + sha256hex(tar.extractfile(member).read()) != h:
                print(f"FAIL hash: {install_path}")
                errors += 1
    if errors:
        print(f"Verification FAILED ({errors})")
        return False
    print(f"Verification OK — {len(mf['files'])} files, "
          f"flatsize {mf['flatsize']:,}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--version", required=True)
    p.add_argument("--revision", type=int, default=1)
    p.add_argument("--out", required=True)
    p.add_argument("--sbin", help="path to the PyInstaller unifi-gateway binary")
    p.add_argument("--no-binary", action="store_true",
                   help="build a UI-only package (development only)")
    p.add_argument("--verify", action="store_true")
    args = p.parse_args()

    sbin = None
    if args.sbin:
        sbin = Path(args.sbin)
        if not sbin.is_file():
            sys.exit(f"ERROR: --sbin binary not found: {sbin}")
    elif not args.no_binary:
        sys.exit("ERROR: no daemon binary supplied. Pass --sbin <binary> "
                 "or --no-binary for a UI-only development build.")
    else:
        print("WARNING: building WITHOUT the daemon binary (development only)")

    out = Path(args.out)
    build(args.version, args.revision, out, sbin)
    if args.verify:
        sys.exit(0 if verify(out) else 1)


if __name__ == "__main__":
    main()
