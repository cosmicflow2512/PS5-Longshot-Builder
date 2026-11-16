#!/usr/bin/env bash
set -euo pipefail
mkdir -p "${CONFIG_DIR:-/config}/logs" "${CONFIG_DIR:-/config}/home"
exec python3 -u /app/webui/app.py
