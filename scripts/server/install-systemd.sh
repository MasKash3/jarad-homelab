#!/usr/bin/env bash
set -euo pipefail

REMOTE_ROOT="${1:-$HOME/mobile}"
SERVICE_USER="${2:-$(id -un)}"
TEMPLATE_DIR="$REMOTE_ROOT/deploy/systemd"

if [ ! -d "$TEMPLATE_DIR" ]; then
  echo "Missing systemd template directory: $TEMPLATE_DIR" >&2
  exit 1
fi

if [ ! -d "$REMOTE_ROOT/backend/.venv" ]; then
  python3 -m venv "$REMOTE_ROOT/backend/.venv"
fi

# shellcheck disable=SC1091
. "$REMOTE_ROOT/backend/.venv/bin/activate"
pip install -r "$REMOTE_ROOT/backend/requirements.txt"

for legacy_service in homelab-mobile-backend.service homelab-mobile-frontend.service; do
  if systemctl list-unit-files "$legacy_service" --no-legend 2>/dev/null | grep -q "$legacy_service"; then
    sudo systemctl disable --now "$legacy_service" || true
    sudo rm -f "/etc/systemd/system/$legacy_service"
  fi
done

for service in jarad-backend.service jarad-frontend.service; do
  sed \
    -e "s#__REMOTE_ROOT__#$REMOTE_ROOT#g" \
    -e "s#__USER__#$SERVICE_USER#g" \
    "$TEMPLATE_DIR/$service" > "/tmp/$service"
  sudo install -m 0644 "/tmp/$service" "/etc/systemd/system/$service"
done

sudo systemctl daemon-reload
sudo systemctl reset-failed
sudo systemctl enable --now jarad-backend.service
sudo systemctl enable --now jarad-frontend.service

echo "Installed and started jarad-backend.service and jarad-frontend.service."
