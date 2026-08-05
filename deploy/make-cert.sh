#!/usr/bin/env bash
# Generate a self-signed certificate for the nginx container.
#
# This is the interim measure until PaintOmics has a DNS name and a trusted
# certificate. Browsers will show a warning; that is expected and is why HSTS
# stays commented out in nginx/paintomics.conf.
#
#   ./deploy/make-cert.sh 161.111.18.82
#
# Output goes to deploy/nginx/certs/, which is gitignored -- the private key
# must never be committed.
set -euo pipefail

HOST="${1:-}"
if [ -z "${HOST}" ]; then
    echo "usage: $0 <hostname-or-ip>" >&2
    exit 1
fi

CERT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/nginx/certs"
mkdir -p "${CERT_DIR}"

if [ -f "${CERT_DIR}/paintomics.key" ]; then
    echo "refusing to overwrite the existing key at ${CERT_DIR}/paintomics.key" >&2
    echo "delete it explicitly if you really mean to replace the certificate" >&2
    exit 1
fi

# A bare IP has to go in subjectAltName as IP:, not DNS: -- browsers and curl
# ignore the CN entirely and reject a DNS: entry holding an address.
if [[ "${HOST}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    SAN="IP:${HOST}"
else
    SAN="DNS:${HOST}"
fi

openssl req -x509 -nodes -newkey rsa:4096 -sha256 -days 825 \
    -keyout "${CERT_DIR}/paintomics.key" \
    -out    "${CERT_DIR}/paintomics.crt" \
    -subj   "/CN=${HOST}/O=PaintOmics/OU=CSIC" \
    -addext "subjectAltName=${SAN}" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth"

chmod 600 "${CERT_DIR}/paintomics.key"
chmod 644 "${CERT_DIR}/paintomics.crt"

echo "wrote ${CERT_DIR}/paintomics.{crt,key} for ${SAN}"
openssl x509 -in "${CERT_DIR}/paintomics.crt" -noout -subject -dates -ext subjectAltName
