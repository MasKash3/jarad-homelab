#!/usr/bin/env bash
set -euo pipefail

readonly DEFAULT_STATE_DIR="/var/lib/scrutiny"
readonly DEFAULT_PORT="8080"
readonly MANAGED_HEADER="# Managed by configure-scrutiny-telegram.sh"

usage() {
  cat <<'EOF'
Usage:
  sudo configure-scrutiny-telegram.sh [--chat <chat-id>] [options]

Options:
  --chat <chat-id>      Telegram numeric chat ID, channel name, or topic ID.
                        If omitted, the helper discovers chats after the bot
                        has received a message.
  --state-dir <path>    Scrutiny state root. Default: /var/lib/scrutiny
  --port <port>         Localhost Scrutiny web port. Default: 8080
  --help                Show this help text.

The bot token is always requested with a hidden interactive prompt. It is
stored only in Scrutiny's root-readable configuration file, not in Docker
environment variables or command-line arguments.
EOF
}

state_dir="$DEFAULT_STATE_DIR"
port="$DEFAULT_PORT"
chat_id=""
token=""
temp_file=""

cleanup() {
  unset token
  if [[ -n "$temp_file" && -f "$temp_file" ]]; then
    rm -f -- "$temp_file"
  fi
}
trap cleanup EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --chat)
      chat_id="${2:-}"
      shift 2
      ;;
    --state-dir)
      state_dir="${2:-}"
      shift 2
      ;;
    --port)
      port="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ "$EUID" -eq 0 ]] || {
  echo "Run this helper with sudo." >&2
  exit 77
}
command -v docker >/dev/null 2>&1 || {
  echo "Docker is required." >&2
  exit 69
}
command -v curl >/dev/null 2>&1 || {
  echo "curl is required." >&2
  exit 69
}
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required for safe Telegram chat discovery." >&2
  exit 69
}
[[ "$state_dir" == /* && "$state_dir" != "/" ]] || {
  echo "--state-dir must be an absolute path other than /." >&2
  exit 2
}
[[ "$port" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )) || {
  echo "--port must be an integer from 1 to 65535." >&2
  exit 2
}
docker container inspect scrutiny >/dev/null 2>&1 || {
  echo "The scrutiny container does not exist." >&2
  exit 69
}
[[ -r /dev/tty && -w /dev/tty ]] || {
  echo "An interactive terminal is required to read the bot token securely." >&2
  exit 69
}

read -r -s -p "Telegram bot token: " token </dev/tty
printf '\n' >/dev/tty
[[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || {
  echo "The Telegram bot token format is invalid." >&2
  exit 2
}

if [[ -z "$chat_id" ]]; then
  echo "Looking for chats that have messaged this bot..."
  mapfile -t discovered_chats < <(
    printf '%s' "$token" | python3 -c '
import json
import sys
import urllib.error
import urllib.request

token = sys.stdin.read().strip()
request = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/getUpdates",
    headers={"Accept": "application/json", "User-Agent": "Jarad-Scrutiny-Setup/1"},
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
    print(f"Telegram chat discovery failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
if payload.get("ok") is not True:
    description = payload.get("description", "unknown error")
    print(f"Telegram rejected chat discovery: {description}", file=sys.stderr)
    raise SystemExit(1)

chats = {}
for update in payload.get("result", []):
    message = update.get("message") or update.get("channel_post") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        continue
    label = chat.get("title") or chat.get("username") or chat.get("first_name") or "Telegram chat"
    chats[str(chat_id)] = " ".join(str(label).split())[:80]

for chat_id, label in chats.items():
    print(f"{chat_id}\t{label}")
'
  )

  if [[ "${#discovered_chats[@]}" -eq 0 ]]; then
    echo "No Telegram chats were found." >&2
    echo "Send /start to the bot (or a message in its group), then run this helper again." >&2
    exit 65
  elif [[ "${#discovered_chats[@]}" -eq 1 ]]; then
    chat_id="${discovered_chats[0]%%$'\t'*}"
    echo "Using Telegram chat: ${discovered_chats[0]#*$'\t'} ($chat_id)"
  else
    echo "Multiple Telegram chats were found:"
    printf '  %s\n' "${discovered_chats[@]}"
    read -r -p "Chat ID to use: " chat_id </dev/tty
  fi
fi

if [[ ! "$chat_id" =~ ^-?[0-9]+(:[0-9]+)?$ && ! "$chat_id" =~ ^@[A-Za-z0-9_]{5,}$ ]]; then
  echo "Chat must be a numeric Telegram chat ID, optional topic ID, or @channel name." >&2
  exit 2
fi

config_dir="$state_dir/config"
config_file="$config_dir/scrutiny.yaml"
install -d -o root -g root -m 0750 "$state_dir" "$config_dir"

if [[ -s "$config_file" ]] && [[ "$(head -n 1 "$config_file")" != "$MANAGED_HEADER" ]]; then
  echo "Refusing to overwrite the existing unmanaged Scrutiny config: $config_file" >&2
  echo "Add the Telegram URL to its notify.urls list manually instead." >&2
  exit 65
fi

umask 077
temp_file="$(mktemp "$config_dir/.scrutiny.yaml.XXXXXX")"
{
  printf '%s\n' "$MANAGED_HEADER"
  printf '%s\n' "version: 1"
  printf '%s\n' "notify:"
  printf '%s\n' "  urls:"
  printf "  - 'telegram://%s@telegram?chats=%s'\n" "$token" "$chat_id"
} >"$temp_file"
install -o root -g root -m 0600 "$temp_file" "$config_file"
rm -f -- "$temp_file"
temp_file=""
unset token

docker restart scrutiny >/dev/null

ready=false
for _ in {1..30}; do
  if curl -fsS --max-time 2 "http://127.0.0.1:${port}/api/health" >/dev/null; then
    ready=true
    break
  fi
  sleep 1
done
[[ "$ready" == true ]] || {
  echo "Scrutiny did not become healthy after restart." >&2
  docker logs --tail 50 scrutiny >&2 || true
  exit 70
}

curl -fsS --max-time 15 -X POST "http://127.0.0.1:${port}/api/health/notify" >/dev/null
echo "Telegram notifications are configured and a test notification was sent."
