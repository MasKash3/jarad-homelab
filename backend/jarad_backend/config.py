from __future__ import annotations

import os
from pathlib import Path


def load_dotenv() -> None:
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_dotenv()


def env(name: str, default: str, legacy_name: str | None = None) -> str:
    if name in os.environ:
        return os.environ[name]
    if legacy_name and legacy_name in os.environ:
        return os.environ[legacy_name]
    return default


APP_TOKEN = env("JARAD_APP_TOKEN", "change-this-long-random-token", "HOMELAB_APP_TOKEN")
TOTP_SECRET = "".join(env("JARAD_TOTP_SECRET", "", "HOMELAB_TOTP_SECRET").split())
PUBLIC_HOST = env("JARAD_PUBLIC_HOST", "home.example", "HOMELAB_PUBLIC_HOST")
LAN_IP = env("JARAD_LAN_IP", "10.0.0.10", "HOMELAB_LAN_IP")
DATA_MOUNT = Path(env("JARAD_DATA_MOUNT", "/mnt/data", "HOMELAB_DATA_MOUNT"))
BACKUP_LOG = Path(env("JARAD_BACKUP_LOG", "/var/log/server-backup.log", "HOMELAB_BACKUP_LOG"))
DNS_SERVER = env("JARAD_DNS_SERVER", "10.0.0.10", "HOMELAB_DNS_SERVER")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in env(
        "JARAD_ALLOWED_ORIGINS",
        "http://127.0.0.1:5178,http://localhost:5178,http://10.0.0.10:5178,https://jarad.example.ts.net:8444",
        "HOMELAB_ALLOWED_ORIGINS",
    ).split(",")
    if origin.strip()
]

SERVICES: dict[str, dict[str, str]] = {
    "nextcloud": {
        "name": "Nextcloud",
        "type": "Files",
        "icon": "NC",
        "container": "nextcloud-app-1",
        "image": "nextcloud:apache",
        "url": f"https://{PUBLIC_HOST}",
        "color": "#2563a6",
    },
    "immich": {
        "name": "Immich",
        "type": "Photos",
        "icon": "IM",
        "container": "immich_server",
        "image": "ghcr.io/immich-app/immich-server:release",
        "url": f"https://{PUBLIC_HOST}:2283",
        "color": "#0f766e",
    },
    "jellyfin": {
        "name": "Jellyfin",
        "type": "Media",
        "icon": "JF",
        "container": "jellyfin",
        "image": "jellyfin/jellyfin:latest",
        "url": f"https://{PUBLIC_HOST}:8096",
        "color": "#7c3aed",
    },
    "portainer": {
        "name": "Portainer",
        "type": "Docker UI",
        "icon": "PT",
        "container": "portainer",
        "image": "portainer/portainer-ce:latest",
        "url": f"https://{PUBLIC_HOST}:9000",
        "color": "#0ea5e9",
    },
    "pihole": {
        "name": "Pi-hole",
        "type": "DNS",
        "icon": "PH",
        "container": "pihole",
        "image": "pihole/pihole:latest",
        "url": f"https://{PUBLIC_HOST}:8053",
        "color": "#dc2626",
    },
    "dozzle": {
        "name": "Dozzle",
        "type": "Logs",
        "icon": "DZ",
        "container": "dozzle",
        "image": "amir20/dozzle:latest",
        "url": f"https://{PUBLIC_HOST}:8082",
        "color": "#334155",
    },
    "uptime-kuma": {
        "name": "Uptime Kuma",
        "type": "Monitor",
        "icon": "UK",
        "container": "uptime-kuma",
        "image": "louislam/uptime-kuma:latest",
        "url": f"https://{PUBLIC_HOST}:3001",
        "color": "#16a34a",
    },
    "stirling-pdf": {
        "name": "Stirling PDF",
        "type": "Tools",
        "icon": "SP",
        "container": "stirling-pdf",
        "image": "frooodle/s-pdf:latest",
        "url": f"https://{PUBLIC_HOST}:8081",
        "color": "#ca8a04",
    },
}
