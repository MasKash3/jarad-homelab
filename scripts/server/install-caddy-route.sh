#!/usr/bin/env bash
set -euo pipefail

REMOTE_ROOT="${1:-$HOME/mobile}"
TAILSCALE_DOMAIN="${2:-}"
APP_PORT="${3:-8444}"
CADDYFILE="${4:-$HOME/caddy/Caddyfile}"
TEMPLATE="$REMOTE_ROOT/deploy/caddy/jarad.Caddyfile"

if [ -z "$TAILSCALE_DOMAIN" ]; then
  echo "Usage: install-caddy-route.sh <remote-root> <tailscale-domain> [app-port] [caddyfile]" >&2
  exit 1
fi

if [ ! -f "$TEMPLATE" ]; then
  echo "Missing Caddy template: $TEMPLATE" >&2
  exit 1
fi

if [ ! -f "$CADDYFILE" ]; then
  echo "Missing Caddyfile: $CADDYFILE" >&2
  exit 1
fi

tmp_rendered="$(mktemp)"
tmp_clean="$(mktemp)"
tmp_new="$(mktemp)"

sed \
  -e "s#__TAILSCALE_DOMAIN__#$TAILSCALE_DOMAIN#g" \
  -e "s#__APP_PORT__#$APP_PORT#g" \
  "$TEMPLATE" > "$tmp_rendered"

awk '
  /^# jarad:start$/ { skip = 1; next }
  /^# jarad:end$/ { skip = 0; next }
  /^# homelab-mobile:start$/ { skip = 1; next }
  /^# homelab-mobile:end$/ { skip = 0; next }
  skip != 1 { print }
' "$CADDYFILE" > "$tmp_clean"

cat "$tmp_clean" "$tmp_rendered" > "$tmp_new"

if ! docker exec -i caddy caddy validate --config /dev/stdin < "$tmp_new"; then
  rm -f "$tmp_rendered" "$tmp_clean" "$tmp_new"
  echo "Generated Caddyfile failed validation; existing config was not changed." >&2
  exit 1
fi

backup="$CADDYFILE.bak-$(date +%Y%m%d-%H%M%S)"
sudo cp "$CADDYFILE" "$backup"
sudo install -m 0644 "$tmp_new" "$CADDYFILE"
if ! docker restart caddy; then
  sudo install -m 0644 "$backup" "$CADDYFILE"
  docker restart caddy || true
  rm -f "$tmp_rendered" "$tmp_clean" "$tmp_new"
  echo "Caddy restart failed; restored previous Caddyfile from $backup." >&2
  exit 1
fi

rm -f "$tmp_rendered" "$tmp_clean" "$tmp_new"

echo "Installed Caddy route: https://$TAILSCALE_DOMAIN:$APP_PORT"
