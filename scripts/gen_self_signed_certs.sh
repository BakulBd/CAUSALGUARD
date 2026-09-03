#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="$(dirname "$SCRIPT_DIR")/deploy/nginx/certs"
mkdir -p "$CERT_DIR"

if [[ -f "$CERT_DIR/privkey.pem" && -f "$CERT_DIR/fullchain.pem" && "${FORCE:-0}" != "1" ]]; then
  echo "Certs already present in $CERT_DIR (set FORCE=1 to regenerate)."
  exit 0
fi

CN="${CERT_CN:-localhost}"
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout "$CERT_DIR/privkey.pem" \
  -out "$CERT_DIR/fullchain.pem" \
  -subj "/CN=${CN}/O=CausalGuard/OU=Dev" \
  -addext "subjectAltName=DNS:${CN},DNS:localhost,IP:127.0.0.1"
chmod 600 "$CERT_DIR/privkey.pem"
echo "Wrote self-signed cert for CN=${CN} to $CERT_DIR"
