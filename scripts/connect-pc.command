#!/bin/bash
# Maintain a private browser tunnel; --install enables background login startup.
set -euo pipefail
SPEAKLAB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec /usr/bin/python3 "$SPEAKLAB_ROOT/scripts/pc_connection.py" "$@"
