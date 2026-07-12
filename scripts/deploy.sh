#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user> [options]

Options:
  --remote-root <path>       Remote app root. Default: ~/mobile
  --frontend-only            Deploy only frontend files
  --backend-only             Deploy only backend files and deployment helpers
  --install-services         Install and enable systemd services
  --install-caddy            Install/update the Caddy route for Tailscale HTTPS
  --caddy-domain <domain>    Tailscale domain for the Caddy HTTPS route
  --caddy-app-port <port>    External Caddy app port. Default: 8444
  --caddyfile <path>         Remote Caddyfile path. Default: ~/caddy/Caddyfile
  --restart-services         Restart frontend and backend systemd services
  --restart-frontend         Restart only the frontend systemd service
  --restart-backend          Restart only the backend systemd service
  --install-backend-deps     Create/update backend venv and install requirements
  --help                     Show this help text

Examples:
  bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user>
  bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user> --restart-services
  bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user> --backend-only --install-caddy --caddy-domain <device.tailnet.ts.net>
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command '$1' was not found on PATH." >&2
    exit 1
  fi
}

run() {
  printf '>'
  for arg in "$@"; do
    printf ' %q' "$arg"
  done
  printf '\n'
  "$@"
}

read_value() {
  local option="$1"
  local value="${2:-}"
  if [[ -z "$value" || "$value" == --* ]]; then
    echo "$option requires a value." >&2
    exit 1
  fi
  printf '%s' "$value"
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
local_config="$repo_root/deploy/local.env"

if [[ -f "$local_config" ]]; then
  # shellcheck disable=SC1090
  source "$local_config"
fi

host_name="${JARAD_DEPLOY_HOST:-${HOMELAB_DEPLOY_HOST:-}}"
user_name="${JARAD_DEPLOY_USER:-${HOMELAB_DEPLOY_USER:-}}"
remote_root="${JARAD_REMOTE_ROOT:-${HOMELAB_REMOTE_ROOT:-~/mobile}}"
frontend_only=false
backend_only=false
install_services=false
install_caddy=false
restart_services=false
restart_frontend=false
restart_backend=false
install_backend_deps=false
caddy_domain="${JARAD_CADDY_DOMAIN:-${HOMELAB_CADDY_DOMAIN:-}}"
caddy_app_port="${JARAD_CADDY_APP_PORT:-${HOMELAB_CADDY_APP_PORT:-8444}}"
caddyfile="${JARAD_CADDYFILE:-${HOMELAB_CADDYFILE:-~/caddy/Caddyfile}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      host_name="$(read_value "$1" "${2:-}")"
      shift 2
      ;;
    --user)
      user_name="$(read_value "$1" "${2:-}")"
      shift 2
      ;;
    --remote-root)
      remote_root="$(read_value "$1" "${2:-}")"
      shift 2
      ;;
    --frontend-only)
      frontend_only=true
      shift
      ;;
    --backend-only)
      backend_only=true
      shift
      ;;
    --install-services)
      install_services=true
      shift
      ;;
    --install-caddy)
      install_caddy=true
      shift
      ;;
    --caddy-domain)
      caddy_domain="$(read_value "$1" "${2:-}")"
      shift 2
      ;;
    --caddy-app-port)
      caddy_app_port="$(read_value "$1" "${2:-}")"
      shift 2
      ;;
    --caddyfile)
      caddyfile="$(read_value "$1" "${2:-}")"
      shift 2
      ;;
    --restart-services)
      restart_services=true
      shift
      ;;
    --restart-frontend)
      restart_frontend=true
      shift
      ;;
    --restart-backend)
      restart_backend=true
      shift
      ;;
    --install-backend-deps)
      install_backend_deps=true
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$host_name" || -z "$user_name" ]]; then
  echo "--host and --user are required." >&2
  usage >&2
  exit 1
fi

if [[ "$frontend_only" == true && "$backend_only" == true ]]; then
  echo "--frontend-only and --backend-only cannot be used together." >&2
  exit 1
fi

if [[ "$install_caddy" == true && -z "$caddy_domain" ]]; then
  echo "--install-caddy requires --caddy-domain <device.tailnet.ts.net>." >&2
  exit 1
fi

require_command ssh
require_command scp
require_command sha256sum
frontend_path="$repo_root/frontend"
backend_path="$repo_root/backend"
server_scripts_path="$repo_root/scripts/server"
systemd_path="$repo_root/deploy/systemd"
caddy_path="$repo_root/deploy/caddy"
remote="${user_name}@${host_name}"
manifest_file="$(mktemp)"
trap 'rm -f "$manifest_file"' EXIT

append_manifest_file() {
  local local_file="$1"
  local remote_path="$2"
  local digest

  if [[ ! -f "$local_file" ]]; then
    return
  fi

  digest="$(sha256sum "$local_file" | awk '{print $1}')"
  printf '%s  %s\n' "$digest" "$remote_path" >> "$manifest_file"
}

append_manifest_tree() {
  local local_dir="$1"
  local remote_prefix="$2"
  local rel_path

  if [[ ! -d "$local_dir" ]]; then
    return
  fi

  while IFS= read -r -d '' rel_path; do
    rel_path="${rel_path#./}"
    append_manifest_file "$local_dir/$rel_path" "$remote_prefix/$rel_path"
  done < <(cd "$local_dir" && find . -type f -print0 | sort -z)
}

build_deploy_manifest() {
  : > "$manifest_file"

  if [[ "$backend_only" != true ]]; then
    append_manifest_tree "$frontend_path" "frontend"
  fi

  if [[ "$frontend_only" != true ]]; then
    append_manifest_tree "$backend_path/jarad_backend" "backend/jarad_backend"
    append_manifest_file "$backend_path/requirements.txt" "backend/requirements.txt"
    append_manifest_file "$backend_path/requirements.lock" "backend/requirements.lock"
    append_manifest_file "$backend_path/README.md" "backend/README.md"
    append_manifest_file "$server_scripts_path/restart-backend.sh" "scripts/server/restart-backend.sh"
    append_manifest_file "$server_scripts_path/install-systemd.sh" "scripts/server/install-systemd.sh"
    append_manifest_file "$server_scripts_path/install-caddy-route.sh" "scripts/server/install-caddy-route.sh"
    append_manifest_file "$server_scripts_path/jarad-dns-access" "scripts/server/jarad-dns-access"
    append_manifest_file "$server_scripts_path/jarad-docker" "scripts/server/jarad-docker"
    append_manifest_file "$systemd_path/jarad-backend.service" "deploy/systemd/jarad-backend.service"
    append_manifest_file "$systemd_path/jarad-frontend.service" "deploy/systemd/jarad-frontend.service"
    append_manifest_file "$caddy_path/jarad.Caddyfile" "deploy/caddy/jarad.Caddyfile"
  elif [[ "$install_caddy" == true ]]; then
    append_manifest_file "$server_scripts_path/install-caddy-route.sh" "scripts/server/install-caddy-route.sh"
    append_manifest_file "$caddy_path/jarad.Caddyfile" "deploy/caddy/jarad.Caddyfile"
  fi
}

verify_deploy_manifest() {
  if [[ ! -s "$manifest_file" ]]; then
    return
  fi

  echo "Verifying deployed file hashes..."
  run scp "$manifest_file" "$remote:$remote_root/deploy/jarad-deploy.sha256"
  run ssh "$remote" "cd $remote_root && sha256sum -c deploy/jarad-deploy.sha256"
}

if [[ ! -d "$frontend_path" ]]; then
  echo "Missing frontend directory: $frontend_path" >&2
  exit 1
fi

if [[ ! -d "$backend_path" ]]; then
  echo "Missing backend directory: $backend_path" >&2
  exit 1
fi

if [[ "$frontend_only" != true && ! -f "$backend_path/requirements.lock" ]]; then
  echo "Missing backend/requirements.lock; refusing an unhashed backend deployment." >&2
  exit 1
fi

run ssh "$remote" "mkdir -p $remote_root/frontend $remote_root/backend $remote_root/scripts/server $remote_root/deploy/systemd $remote_root/deploy/caddy"

if [[ "$backend_only" != true ]]; then
  echo "Deploying frontend..."
  run scp -r "$frontend_path"/* "$remote:$remote_root/frontend/"
fi

if [[ "$frontend_only" != true ]]; then
  echo "Deploying backend..."
  run scp -r \
    "$backend_path/jarad_backend" \
    "$backend_path/requirements.txt" \
    "$backend_path/requirements.lock" \
    "$backend_path/README.md" \
    "$remote:$remote_root/backend/"

  run scp "$server_scripts_path/restart-backend.sh" "$remote:$remote_root/scripts/server/restart-backend.sh"
  run scp "$server_scripts_path/install-systemd.sh" "$remote:$remote_root/scripts/server/install-systemd.sh"
  run scp "$server_scripts_path/install-caddy-route.sh" "$remote:$remote_root/scripts/server/install-caddy-route.sh"
  run scp "$server_scripts_path/jarad-dns-access" "$remote:$remote_root/scripts/server/jarad-dns-access"
  run scp "$server_scripts_path/jarad-docker" "$remote:$remote_root/scripts/server/jarad-docker"
  run scp \
    "$systemd_path/jarad-backend.service" \
    "$systemd_path/jarad-frontend.service" \
    "$remote:$remote_root/deploy/systemd/"
  run scp "$caddy_path/jarad.Caddyfile" "$remote:$remote_root/deploy/caddy/jarad.Caddyfile"

  run ssh "$remote" "chmod +x $remote_root/scripts/server/restart-backend.sh $remote_root/scripts/server/install-systemd.sh $remote_root/scripts/server/install-caddy-route.sh $remote_root/scripts/server/jarad-dns-access $remote_root/scripts/server/jarad-docker"
fi

if [[ "$install_caddy" == true && "$frontend_only" == true ]]; then
  echo "Deploying Caddy installer..."
  run scp "$server_scripts_path/install-caddy-route.sh" "$remote:$remote_root/scripts/server/install-caddy-route.sh"
  run scp "$caddy_path/jarad.Caddyfile" "$remote:$remote_root/deploy/caddy/jarad.Caddyfile"
  run ssh "$remote" "chmod +x $remote_root/scripts/server/install-caddy-route.sh"
fi

build_deploy_manifest
verify_deploy_manifest

if [[ "$install_backend_deps" == true ]]; then
  echo "Installing backend dependencies..."
  run ssh "$remote" "cd $remote_root/backend && test -f requirements.lock && python3 -m venv .venv && . .venv/bin/activate && pip install --require-hashes -r requirements.lock"
fi

if [[ "$install_services" == true ]]; then
  echo "Installing systemd services..."
  run ssh -tt "$remote" "$remote_root/scripts/server/install-systemd.sh $remote_root $user_name"
fi

if [[ "$install_caddy" == true ]]; then
  echo "Installing Caddy route..."
  run ssh -tt "$remote" "$remote_root/scripts/server/install-caddy-route.sh $remote_root $caddy_domain $caddy_app_port $caddyfile"
fi

if [[ "$restart_backend" == true ]]; then
  echo "Restarting backend..."
  run ssh -tt "$remote" "sudo systemctl restart jarad-backend.service"
fi

if [[ "$restart_frontend" == true ]]; then
  echo "Restarting frontend..."
  run ssh -tt "$remote" "sudo systemctl restart jarad-frontend.service"
fi

if [[ "$restart_services" == true ]]; then
  echo "Restarting frontend and backend services..."
  run ssh -tt "$remote" "sudo systemctl restart jarad-backend.service jarad-frontend.service"
fi

echo "Deploy complete."
