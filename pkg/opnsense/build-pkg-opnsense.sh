#!/bin/sh
# Build the os-unifi-gateway OPNsense plugin package.
# Usage: build-pkg-opnsense.sh <version> [--sbin <unifi-gateway-binary>] [--no-binary]
set -e

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

VERSION="$1"
if [ -z "$VERSION" ]; then
    echo "usage: build-pkg-opnsense.sh <version> [--sbin <binary>] [--no-binary]" >&2
    exit 1
fi
shift

mkdir -p "$REPO_ROOT/dist"
exec python3 "$SCRIPT_DIR/scripts/build_pkg_opnsense.py" \
    --version "$VERSION" \
    --out "$REPO_ROOT/dist/os-unifi-gateway-$VERSION.pkg" \
    --verify "$@"
