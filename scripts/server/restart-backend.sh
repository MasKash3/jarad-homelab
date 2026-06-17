#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR/backend"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
. .venv/bin/activate
pip install -r requirements.txt

backend_port="${JARAD_BACKEND_PORT:-${HOMELAB_BACKEND_PORT:-8443}}"

pkill -f "uvicorn jarad_backend.main:app" 2>/dev/null || true
nohup uvicorn jarad_backend.main:app --host 0.0.0.0 --port "$backend_port" > backend.out.log 2> backend.err.log &

echo "Backend restarted on port $backend_port."
