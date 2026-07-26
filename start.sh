#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"
exec python3 server.py --port "${YANFLOW_PORT:-8786}"
