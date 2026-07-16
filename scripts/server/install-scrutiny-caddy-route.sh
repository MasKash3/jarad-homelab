#!/usr/bin/env bash
set -euo pipefail

REMOTE_ROOT="${1:-$HOME/mobile}"
TAILSCALE_DOMAIN="${2:-}"
EXTERNAL_PORT="${3:-8445}"
UPSTREAM_PORT="${4:-8080}"
CADDYFILE="${5:-$HOME/caddy/Caddyfile}"
TEMPLATE="$REMOTE_ROOT/deploy/caddy/scrutiny.Caddyfile"

if [[ -z "$TAILSCALE_DOMAIN" ]]; then
  echo "Usage: install-scrutiny-caddy-route.sh <remote-root> <tailscale-domain> [external-port] [upstream-port] [caddyfile]" >&2
  exit 1
fi

if (( ${#TAILSCALE_DOMAIN} > 253 )) \
  || [[ ! "$TAILSCALE_DOMAIN" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$ ]] \
  || [[ "$TAILSCALE_DOMAIN" != *.* || "$TAILSCALE_DOMAIN" == *..* || "$TAILSCALE_DOMAIN" == *"*"* ]]; then
  echo "Caddy domain must be one exact DNS hostname without a wildcard." >&2
  exit 1
fi
IFS='.' read -r -a domain_labels <<<"$TAILSCALE_DOMAIN"
for label in "${domain_labels[@]}"; do
  if (( ${#label} > 63 )) || [[ ! "$label" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]]; then
    echo "Caddy domain contains an invalid DNS label." >&2
    exit 1
  fi
done

for port in "$EXTERNAL_PORT" "$UPSTREAM_PORT"; do
  if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    echo "Caddy ports must be integers from 1 to 65535." >&2
    exit 1
  fi
done

[[ -f "$TEMPLATE" ]] || {
  echo "Missing Caddy template: $TEMPLATE" >&2
  exit 1
}
[[ -f "$CADDYFILE" ]] || {
  echo "Missing Caddyfile: $CADDYFILE" >&2
  exit 1
}

tmp_rendered="$(mktemp)"
tmp_clean="$(mktemp)"
tmp_new="$(mktemp)"
trap 'rm -f "$tmp_rendered" "$tmp_clean" "$tmp_new"' EXIT

sed \
  -e "s#__TAILSCALE_DOMAIN__#$TAILSCALE_DOMAIN#g" \
  -e "s#__EXTERNAL_PORT__#$EXTERNAL_PORT#g" \
  -e "s#__UPSTREAM_PORT__#$UPSTREAM_PORT#g" \
  "$TEMPLATE" > "$tmp_rendered"

awk '
  /^# scrutiny:start$/ { skip = 1; next }
  /^# scrutiny:end$/ { skip = 0; next }
  skip != 1 { print }
' "$CADDYFILE" > "$tmp_clean"

cat "$tmp_clean" "$tmp_rendered" > "$tmp_new"

if ! docker exec -i caddy caddy validate --adapter caddyfile --config /dev/stdin < "$tmp_new"; then
  echo "Generated Caddyfile failed validation; existing config was not changed." >&2
  exit 1
fi

backup="$CADDYFILE.bak-$(date +%Y%m%d-%H%M%S)"
sudo cp "$CADDYFILE" "$backup"
sudo install -m 0644 "$tmp_new" "$CADDYFILE"
if ! docker restart caddy; then
  sudo install -m 0644 "$backup" "$CADDYFILE"
  docker restart caddy || true
  echo "Caddy restart failed; restored previous Caddyfile from $backup." >&2
  exit 1
fi

echo "Installed private Scrutiny route: https://$TAILSCALE_DOMAIN:$EXTERNAL_PORT"
