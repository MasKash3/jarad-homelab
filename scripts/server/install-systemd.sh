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

if [ -f "$REMOTE_ROOT/backend/.env" ]; then
  chmod 600 "$REMOTE_ROOT/backend/.env"
fi

# shellcheck disable=SC1091
. "$REMOTE_ROOT/backend/.venv/bin/activate"
if [ -f "$REMOTE_ROOT/backend/requirements.lock" ]; then
  pip install --require-hashes -r "$REMOTE_ROOT/backend/requirements.lock"
else
  pip install -r "$REMOTE_ROOT/backend/requirements.txt"
fi

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

if [ -f "$REMOTE_ROOT/scripts/server/jarad-dns-access" ]; then
  sudo install -m 0755 "$REMOTE_ROOT/scripts/server/jarad-dns-access" /usr/local/sbin/jarad-dns-access
  sudo tee /etc/sudoers.d/jarad-dns-access >/dev/null <<EOF
$SERVICE_USER ALL=(root) NOPASSWD: /usr/local/sbin/jarad-dns-access detect
$SERVICE_USER ALL=(root) NOPASSWD: /usr/local/sbin/jarad-dns-access apply *
EOF
  sudo chmod 0440 /etc/sudoers.d/jarad-dns-access
  sudo visudo -cf /etc/sudoers.d/jarad-dns-access >/dev/null
fi

sudo systemctl daemon-reload
sudo systemctl reset-failed
sudo systemctl enable --now jarad-backend.service
sudo systemctl enable --now jarad-frontend.service

echo "Installed and started jarad-backend.service and jarad-frontend.service."
