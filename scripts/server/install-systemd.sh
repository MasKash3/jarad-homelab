#!/usr/bin/env bash
set -euo pipefail

REMOTE_ROOT="${1:-$HOME/mobile}"
DEPLOY_USER="${2:-$(id -un)}"
BACKEND_USER="${3:-jarad-backend}"
FRONTEND_USER="${4:-jarad-frontend}"
RELEASE_COMMIT="${5:-}"
RELEASE_TAG="${6:-}"
TEMPLATE_DIR="$REMOTE_ROOT/deploy/systemd"

ensure_service_account() {
  local account="$1"
  if ! getent group "$account" >/dev/null; then
    sudo groupadd --system "$account"
  fi
  if ! id "$account" >/dev/null 2>&1; then
    sudo useradd --system --gid "$account" --no-create-home --shell /usr/sbin/nologin "$account"
  fi
}

verify_loopback_listener() {
  local service_name="$1"
  local port="$2"
  local listeners

  listeners="$(ss -H -ltn "sport = :$port" 2>/dev/null || true)"
  if [ -z "$listeners" ]; then
    echo "$service_name did not open its expected localhost port $port." >&2
    return 1
  fi
  if awk '{ print $4 }' <<<"$listeners" | grep -Evq '^(127\.0\.0\.1|\[::1\]):[0-9]+$'; then
    echo "$service_name port $port is exposed beyond localhost; refusing this service installation." >&2
    return 1
  fi
}

if [ ! -d "$TEMPLATE_DIR" ]; then
  echo "Missing systemd template directory: $TEMPLATE_DIR" >&2
  exit 1
fi
if [[ ! "$RELEASE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || [[ ! "$RELEASE_TAG" =~ ^v[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]+$ ]]; then
  echo "A full release commit and vYYYY.MM.DD.N release tag are required." >&2
  exit 1
fi

mapfile -t residual_env_files < <(
  find "$REMOTE_ROOT/backend" -maxdepth 1 -type f \
    \( -name '.env.*' -o -name '.env~' -o -name '*.env.bak*' -o -name '*.env.old*' \) \
    ! -name '.env.example' -print
)
if (( ${#residual_env_files[@]} > 0 )); then
  echo "Plaintext environment backup files were found; remove or encrypt them before installing services:" >&2
  printf '  %s\n' "${residual_env_files[@]}" >&2
  exit 1
fi

ENV_SOURCE="$REMOTE_ROOT/backend/.env"
ENV_TARGET="/etc/jarad/backend.env"
if [ -f "$ENV_SOURCE" ]; then
  if grep -Eqi '^[[:space:]]*(JARAD|HOMELAB)_ALLOW_INSECURE_DEFAULTS[[:space:]]*=[[:space:]]*(1|true|yes)[[:space:]]*$' "$ENV_SOURCE"; then
    echo "Production service installation refuses ALLOW_INSECURE_DEFAULTS." >&2
    exit 1
  fi
  if grep -Eqi '^[[:space:]]*(JARAD|HOMELAB)_ALLOW_PASSKEY_BOOTSTRAP_WITHOUT_TOTP[[:space:]]*=[[:space:]]*(1|true|yes)[[:space:]]*$' "$ENV_SOURCE"; then
    echo "Production service installation refuses passkey bootstrap without TOTP." >&2
    exit 1
  fi
elif ! sudo test -f "$ENV_TARGET"; then
  echo "Missing backend environment. Provide $ENV_SOURCE for first migration." >&2
  exit 1
fi

ensure_service_account "$BACKEND_USER"
ensure_service_account "$FRONTEND_USER"

sudo systemctl stop jarad-backend.service jarad-frontend.service 2>/dev/null || true

sudo install -d -o "$BACKEND_USER" -g "$BACKEND_USER" -m 0700 /var/lib/jarad
if [ -f "$REMOTE_ROOT/backend/jarad.sqlite3" ] && [ ! -f /var/lib/jarad/jarad.sqlite3 ]; then
  sudo cp -a "$REMOTE_ROOT/backend/jarad.sqlite3" /var/lib/jarad/jarad.sqlite3
fi
for sidecar in -wal -shm -journal; do
  if [ -f "$REMOTE_ROOT/backend/jarad.sqlite3$sidecar" ] && [ ! -f "/var/lib/jarad/jarad.sqlite3$sidecar" ]; then
    sudo cp -a "$REMOTE_ROOT/backend/jarad.sqlite3$sidecar" "/var/lib/jarad/jarad.sqlite3$sidecar"
  fi
done
sudo chown -R "$BACKEND_USER:$BACKEND_USER" /var/lib/jarad
sudo chmod 0700 /var/lib/jarad
sudo find /var/lib/jarad -maxdepth 1 -type f -name 'jarad.sqlite3*' -exec chmod 0600 {} +

sudo chown -R "$DEPLOY_USER:$BACKEND_USER" "$REMOTE_ROOT/backend"
sudo chmod -R u=rwX,g=rX,o= "$REMOTE_ROOT/backend"
sudo chmod 2750 "$REMOTE_ROOT/backend"

sudo chown -R "$DEPLOY_USER:$FRONTEND_USER" "$REMOTE_ROOT/frontend"
sudo chmod -R u=rwX,g=rX,o= "$REMOTE_ROOT/frontend"
sudo chmod 2750 "$REMOTE_ROOT/frontend"

if [ ! -d "$REMOTE_ROOT/backend/.venv" ]; then
  python3 -m venv "$REMOTE_ROOT/backend/.venv"
fi

if [ -f "$ENV_SOURCE" ]; then
  sudo install -d -o root -g root -m 0755 /etc/jarad
  sudo install -o root -g "$BACKEND_USER" -m 0640 "$ENV_SOURCE" "$ENV_TARGET"
  sudo rm -f "$ENV_SOURCE"
else
  sudo chown root:"$BACKEND_USER" "$ENV_TARGET"
  sudo chmod 0640 "$ENV_TARGET"
fi

# shellcheck disable=SC1091
. "$REMOTE_ROOT/backend/.venv/bin/activate"
if [ ! -f "$REMOTE_ROOT/backend/requirements.lock" ]; then
  echo "Missing backend/requirements.lock; refusing an unhashed dependency install." >&2
  exit 1
fi
pip install --require-hashes -r "$REMOTE_ROOT/backend/requirements.lock"
sudo chown -R "$DEPLOY_USER:$BACKEND_USER" "$REMOTE_ROOT/backend"
sudo chmod -R u=rwX,g=rX,o= "$REMOTE_ROOT/backend"
sudo chmod 2750 "$REMOTE_ROOT/backend"

if [ ! -f "$REMOTE_ROOT/scripts/server/jarad-promote-release" ]; then
  echo "Missing Jarad release promotion helper." >&2
  exit 1
fi
sudo install -o root -g root -m 0755 "$REMOTE_ROOT/scripts/server/jarad-promote-release" /usr/local/sbin/jarad-promote-release
sudo /usr/local/sbin/jarad-promote-release "$REMOTE_ROOT" full "$RELEASE_COMMIT" "$RELEASE_TAG"

for legacy_service in homelab-mobile-backend.service homelab-mobile-frontend.service; do
  if systemctl list-unit-files "$legacy_service" --no-legend 2>/dev/null | grep -q "$legacy_service"; then
    sudo systemctl disable --now "$legacy_service" || true
    sudo rm -f "/etc/systemd/system/$legacy_service"
  fi
done

sed \
  -e "s#__REMOTE_ROOT__#$REMOTE_ROOT#g" \
  -e "s#__BACKEND_USER__#$BACKEND_USER#g" \
  "$TEMPLATE_DIR/jarad-backend.service" > /tmp/jarad-backend.service
sudo install -m 0644 /tmp/jarad-backend.service /etc/systemd/system/jarad-backend.service

sed \
  -e "s#__REMOTE_ROOT__#$REMOTE_ROOT#g" \
  -e "s#__FRONTEND_USER__#$FRONTEND_USER#g" \
  "$TEMPLATE_DIR/jarad-frontend.service" > /tmp/jarad-frontend.service
sudo install -m 0644 /tmp/jarad-frontend.service /etc/systemd/system/jarad-frontend.service

if [ -f "$REMOTE_ROOT/scripts/server/jarad-dns-access" ]; then
  sudo install -m 0755 "$REMOTE_ROOT/scripts/server/jarad-dns-access" /usr/local/sbin/jarad-dns-access
  sudo tee /etc/sudoers.d/jarad-dns-access >/dev/null <<EOF
$BACKEND_USER ALL=(root) NOPASSWD: /usr/local/sbin/jarad-dns-access detect
$BACKEND_USER ALL=(root) NOPASSWD: /usr/local/sbin/jarad-dns-access apply *
EOF
  sudo chmod 0440 /etc/sudoers.d/jarad-dns-access
  sudo visudo -cf /etc/sudoers.d/jarad-dns-access >/dev/null
fi

if [ ! -f "$REMOTE_ROOT/scripts/server/jarad-docker" ]; then
  echo "Missing Jarad Docker policy helper." >&2
  exit 1
fi
sudo install -o root -g root -m 0755 "$REMOTE_ROOT/scripts/server/jarad-docker" /usr/local/sbin/jarad-docker
sudo tee /etc/sudoers.d/jarad-docker >/dev/null <<EOF
$BACKEND_USER ALL=(root) NOPASSWD: /usr/local/sbin/jarad-docker *
EOF
sudo chmod 0440 /etc/sudoers.d/jarad-docker
sudo visudo -cf /etc/sudoers.d/jarad-docker >/dev/null

sudo systemctl daemon-reload
sudo systemctl reset-failed
if sudo -u "$FRONTEND_USER" test -r "$ENV_TARGET"; then
  echo "Frontend service account can read backend secrets; refusing to start services." >&2
  exit 1
fi
if sudo -u "$DEPLOY_USER" test -r "$ENV_TARGET"; then
  echo "Deployment account can read live backend secrets; refusing to start services." >&2
  exit 1
fi
sudo systemctl enable --now jarad-backend.service
sudo systemctl enable --now jarad-frontend.service

verify_loopback_listener jarad-backend.service 8443
verify_loopback_listener jarad-frontend.service 5178

echo "Installed and started jarad-backend.service and jarad-frontend.service."
