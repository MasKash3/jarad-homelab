#!/usr/bin/env bash
set -euo pipefail

readonly DEFAULT_IMAGE="ghcr.io/analogj/scrutiny:v0.9.2-omnibus"
readonly DEFAULT_STATE_DIR="/var/lib/scrutiny"
readonly DEFAULT_PORT="8080"

usage() {
  cat <<'EOF'
Usage:
  install-scrutiny.sh --device <device> [--device <device> ...] [options]

Options:
  --device <path>       Host disk device to expose, for example /dev/sda.
  --state-dir <path>    Persistent data root. Default: /var/lib/scrutiny
  --port <port>         Localhost web port. Default: 8080
  --image <image>       Pinned Scrutiny omnibus image.
  --nvme                Add SYS_ADMIN, required by Scrutiny for NVMe devices.
  --help                Show this help text.

The installer binds Scrutiny to 127.0.0.1 only. Install a private HTTPS reverse
proxy route separately before opening it from another device.
EOF
}

image="$DEFAULT_IMAGE"
state_dir="$DEFAULT_STATE_DIR"
port="$DEFAULT_PORT"
enable_nvme=false
devices=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      [[ -n "${2:-}" && "${2:-}" != --* ]] || {
        echo "--device requires a value." >&2
        exit 2
      }
      devices+=("$2")
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
    --image)
      image="${2:-}"
      shift 2
      ;;
    --nvme)
      enable_nvme=true
      shift
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

command -v docker >/dev/null 2>&1 || {
  echo "Docker is required." >&2
  exit 69
}
[[ -d /run/udev ]] || {
  echo "/run/udev is unavailable; Scrutiny cannot read device metadata." >&2
  exit 69
}
[[ "${#devices[@]}" -gt 0 ]] || {
  echo "At least one explicit --device is required." >&2
  exit 2
}
[[ "$state_dir" == /* && "$state_dir" != "/" ]] || {
  echo "--state-dir must be an absolute path other than /." >&2
  exit 2
}
[[ "$port" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )) || {
  echo "--port must be an integer from 1 to 65535." >&2
  exit 2
}
[[ "$image" =~ ^ghcr\.io/analogj/scrutiny:v[0-9]+\.[0-9]+\.[0-9]+-omnibus$ ]] || {
  echo "--image must be a pinned official Scrutiny omnibus release." >&2
  exit 2
}

device_args=()
for device in "${devices[@]}"; do
  [[ "$device" == /dev/* && "$device" != *[[:space:]]* ]] || {
    echo "Invalid device path: $device" >&2
    exit 2
  }
  [[ -b "$device" || -c "$device" ]] || {
    echo "Device does not exist or is not a block/character device: $device" >&2
    exit 2
  }
  device_args+=(--device "$device:$device")
done

if docker container inspect scrutiny >/dev/null 2>&1; then
  echo "A container named scrutiny already exists; refusing to replace it." >&2
  exit 65
fi

sudo install -d -m 0750 "$state_dir" "$state_dir/config" "$state_dir/influxdb"

capability_args=(--cap-add SYS_RAWIO)
if [[ "$enable_nvme" == true ]]; then
  capability_args+=(--cap-add SYS_ADMIN)
fi

docker pull "$image"
docker run -d \
  --name scrutiny \
  --restart unless-stopped \
  --publish "127.0.0.1:${port}:8080" \
  --volume "$state_dir/config:/opt/scrutiny/config" \
  --volume "$state_dir/influxdb:/opt/scrutiny/influxdb" \
  --volume "/run/udev:/run/udev:ro" \
  "${capability_args[@]}" \
  "${device_args[@]}" \
  "$image"

echo "Scrutiny is running on http://127.0.0.1:${port}."
echo "Verify detected disks before relying on monitoring: docker logs scrutiny"
