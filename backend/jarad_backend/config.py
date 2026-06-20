from __future__ import annotations

import os
from pathlib import Path


def ensure_private_env_file(env_path: Path) -> None:
    if os.name == "nt" or not env_path.exists():
        return

    mode = env_path.stat().st_mode & 0o777
    if mode & 0o077:
        raise RuntimeError(f"Refusing to start because {env_path} permissions are too broad. Run: chmod 600 {env_path}")


def load_dotenv() -> None:
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return

    ensure_private_env_file(env_path)
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


PLACEHOLDER_APP_TOKEN = "change-this-long-random-token"
ALLOW_INSECURE_DEFAULTS = env("JARAD_ALLOW_INSECURE_DEFAULTS", "0", "HOMELAB_ALLOW_INSECURE_DEFAULTS") == "1"
APP_TOKEN = env("JARAD_APP_TOKEN", "", "HOMELAB_APP_TOKEN")
if not APP_TOKEN or (APP_TOKEN == PLACEHOLDER_APP_TOKEN and not ALLOW_INSECURE_DEFAULTS):
    raise RuntimeError("Set JARAD_APP_TOKEN to a long random value before starting Jarad Backend.")
TOTP_SECRET = "".join(env("JARAD_TOTP_SECRET", "", "HOMELAB_TOTP_SECRET").split())
ALLOW_PASSKEY_BOOTSTRAP_WITHOUT_TOTP = (
    env("JARAD_ALLOW_PASSKEY_BOOTSTRAP_WITHOUT_TOTP", "0", "HOMELAB_ALLOW_PASSKEY_BOOTSTRAP_WITHOUT_TOTP") == "1"
)


def positive_int_env(name: str, default: str, legacy_name: str | None = None) -> int:
    raw_value = env(name, default, legacy_name)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


DEVICE_TOKEN_TTL_DAYS = positive_int_env("JARAD_DEVICE_TOKEN_TTL_DAYS", "90", "HOMELAB_DEVICE_TOKEN_TTL_DAYS")
PUBLIC_HOST = env("JARAD_PUBLIC_HOST", "home.example", "HOMELAB_PUBLIC_HOST")
SERVICE_DOMAIN = env("JARAD_SERVICE_DOMAIN", "", "HOMELAB_SERVICE_DOMAIN")
LAN_IP = env("JARAD_LAN_IP", "10.0.0.10", "HOMELAB_LAN_IP")
WEBAUTHN_RP_ID = env("JARAD_WEBAUTHN_RP_ID", PUBLIC_HOST.split(":")[0], "HOMELAB_WEBAUTHN_RP_ID")
WEBAUTHN_ORIGIN = env("JARAD_WEBAUTHN_ORIGIN", f"https://{WEBAUTHN_RP_ID}:8444", "HOMELAB_WEBAUTHN_ORIGIN")
DB_PATH = Path(env("JARAD_DB_PATH", str(Path.cwd() / "jarad.sqlite3"), "HOMELAB_DB_PATH"))
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


def service_url(subdomain: str, legacy_port: int | None = None, path: str = "") -> str:
    if SERVICE_DOMAIN:
        return f"https://{subdomain}.{SERVICE_DOMAIN}{path}"
    port = f":{legacy_port}" if legacy_port else ""
    return f"https://{PUBLIC_HOST}{port}{path}"


SERVICES: dict[str, dict[str, str]] = {
    "nextcloud": {
        "name": "Nextcloud",
        "type": "Files",
        "icon": "NC",
        "container": "nextcloud-app-1",
        "image": "nextcloud:apache",
        "url": service_url("nextcloud"),
        "color": "#2563a6",
    },
    "immich": {
        "name": "Immich",
        "type": "Photos",
        "icon": "IM",
        "container": "immich_server",
        "image": "ghcr.io/immich-app/immich-server:release",
        "url": service_url("immich", 2283),
        "color": "#0f766e",
    },
    "jellyfin": {
        "name": "Jellyfin",
        "type": "Media",
        "icon": "JF",
        "container": "jellyfin",
        "image": "jellyfin/jellyfin:latest",
        "url": service_url("jellyfin", 8096),
        "color": "#7c3aed",
    },
    "portainer": {
        "name": "Portainer",
        "type": "Docker UI",
        "icon": "PT",
        "container": "portainer",
        "image": "portainer/portainer-ce:latest",
        "url": service_url("portainer", 9000),
        "color": "#0ea5e9",
    },
    "pihole": {
        "name": "Pi-hole",
        "type": "DNS",
        "icon": "PH",
        "container": "pihole",
        "image": "pihole/pihole:latest",
        "url": service_url("pihole", 8053, "/admin"),
        "color": "#dc2626",
    },
    "dozzle": {
        "name": "Dozzle",
        "type": "Logs",
        "icon": "DZ",
        "container": "dozzle",
        "image": "amir20/dozzle:latest",
        "url": service_url("dozzle", 8082),
        "color": "#334155",
    },
    "uptime-kuma": {
        "name": "Uptime Kuma",
        "type": "Monitor",
        "icon": "UK",
        "container": "uptime-kuma",
        "image": "louislam/uptime-kuma:latest",
        "url": service_url("uptime", 3001),
        "color": "#16a34a",
    },
    "stirling-pdf": {
        "name": "Stirling PDF",
        "type": "Tools",
        "icon": "SP",
        "container": "stirling-pdf",
        "image": "frooodle/s-pdf:latest",
        "url": service_url("stirling", 8081),
        "color": "#ca8a04",
    },
}
