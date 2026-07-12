#!/usr/bin/env bash
set -euo pipefail

mkdir -p certs

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout certs/localhost.key \
  -out certs/localhost.crt \
  -days 30 \
  -subj '/CN=localhost' \
  -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'

chmod 600 certs/localhost.key
