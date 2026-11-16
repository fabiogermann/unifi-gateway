#!/bin/sh
# Upload a .pkg artifact to ArtifactKeeper through Cloudflare Access.
#
# Three independent credentials (do not conflate):
#   CF-Access-Client-Id/Secret  — gets you PAST Cloudflare Access (service token)
#   Authorization: Bearer       — ArtifactKeeper's own repo-scoped write:artifacts token
#
# Fails closed: only HTTP 201 counts as success. A Cloudflare SSO page returns
# HTTP 200 text/html and a banned client returns 403 "error code: 1010"; both
# must fail the job, never pass as an upload.
set -eu

PKG_FILE="${1:?usage: upload-ak.sh <file.pkg> <repo> <abi>}"
AK_REPO="${2:?missing repo key (e.g. freebsd-pkg)}"
ABI="${3:?missing ABI (e.g. FreeBSD:15:amd64)}"

: "${AK_BASE_URL:?set AK_BASE_URL (e.g. https://ak.intra.sh)}"
: "${AK_WRITE_TOKEN:?set AK_WRITE_TOKEN (repo-scoped write:artifacts token)}"
: "${CF_ACCESS_CLIENT_ID:?set CF_ACCESS_CLIENT_ID}"
: "${CF_ACCESS_CLIENT_SECRET:?set CF_ACCESS_CLIENT_SECRET}"

name="${PKG_FILE##*/}"
checksum=$(sha256sum "$PKG_FILE" | awk '{print $1}')
encoded_abi=$(printf '%s' "$ABI" | sed 's/:/%3A/g')
url="${AK_BASE_URL%/}/api/v1/repositories/${AK_REPO}/artifacts/${encoded_abi}/${name}"

body_file=$(mktemp)
trap 'rm -f "$body_file"' EXIT

# No --fail: status is analysed below (only 201 passes); the || arm here
# catches transport-level failures (DNS, refused, TLS) where code is 000.
code=$(curl --silent --show-error --output "$body_file" \
  --write-out '%{http_code}' \
  --request PUT \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  -H "Authorization: Bearer ${AK_WRITE_TOKEN}" \
  -H "X-Checksum-SHA256: ${checksum}" \
  -H "User-Agent: unifi-gateway-ci (+https://github.com/fabiogermann/unifi-gateway)" \
  -H "Accept: application/json" \
  --upload-file "$PKG_FILE" \
  "$url") || {
  echo "::error::curl-level failure uploading $name (HTTP $code)" >&2
  exit 1
}

if [ "$code" != "201" ]; then
  echo "::error::upload of $name expected HTTP 201, got HTTP $code" >&2
  case "$code" in
    200|301|302|303|307|308)
      echo "::error::got a success/redirect status — likely the Cloudflare Access SSO page. CF-Access-* headers missing, wrong, or no Service Auth policy on the application." >&2 ;;
    403)
      if grep -q 'error code: 1010' "$body_file" 2>/dev/null; then
        echo "::error::403 'error code: 1010' — client/UA banned by Browser Integrity Check before Access evaluated the token. This is a client-side problem, NOT a credential problem." >&2
      else
        echo "::error::403 — service token not authorized for this Access application (missing Service Auth policy)." >&2
      fi ;;
    401)
      echo "::error::401 — Cloudflare Access passed; ArtifactKeeper rejected its own Bearer token (scopes/repo permission)." >&2 ;;
  esac
  exit 1
fi

echo "uploaded ${name} -> ${AK_REPO}/${ABI} (sha256 ${checksum})"
