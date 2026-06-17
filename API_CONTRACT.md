# Jarad Backend API Contract

This app is a mobile-first PWA shell for a private home server. It runs with local demo data until a backend URL and access token are configured in the app settings screen.

Recommended deployment:

- Bind the backend to a private network or an authenticated HTTPS proxy.
- Require app authentication for every endpoint.
- Require fingerprint or TOTP before protected service actions.
- Record auth, diagnostics, log views, and actions in a backend audit store before using this beyond a trusted LAN.

## `GET /api/mobile/state`

Returns the dashboard, service, log, alert, backup, and network state in one mobile-friendly payload.

```json
{
  "updatedAt": "2026-06-15T18:30:00+02:00",
  "server": {
    "name": "Jarad",
    "host": "home.example",
    "lan": "<server-lan-ip>",
    "uptime": "18 days, 7 hours",
    "healthScore": 96,
    "status": "Operational"
  },
  "metrics": [
    { "label": "CPU", "value": 22, "unit": "%", "state": "good" }
  ],
  "storage": {
    "usedPct": 70,
    "label": "1.28 TB used of 1.82 TB",
    "cloudBackup": "Cloud backup 342 GB",
    "raid": "RAID clean"
  },
  "backups": {
    "state": "Healthy",
    "quick": "Today 18:00",
    "full": "Today 06:00",
    "next": "Tonight 00:00"
  },
  "services": [],
  "logs": [],
  "alerts": [],
  "network": [["DNS", "OK"]]
}
```

## `POST /api/auth/totp/check`

```json
{
  "code": "123456"
}
```

Returns whether the backend TOTP secret is configured and whether the submitted code is currently valid.

## `POST /api/admin/actions/{action_id}`

Executes a bounded, whitelisted service action only after fingerprint or TOTP authorization. Initial actions:

- `restart-{service_id}`
- `start-{service_id}`
- `stop-{service_id}`

The backend must not expose arbitrary shell execution.

```json
{
  "source": "mobile-pwa",
  "serviceId": "nextcloud",
  "authMethod": "totp",
  "totpCode": "123456"
}
```

## `GET /api/services/{service_id}/logs`

Returns recent logs for one service. Suggested query params:

- `level=error|warn|info`
- `limit=100`
- `search=...`

## `GET /api/services/{service_id}/diagnostics`

Returns deterministic diagnostic checks and suggested fixes.

```json
{
  "service": "nextcloud",
  "checks": [
    { "label": "Container running", "state": "pass", "detail": "nextcloud-app-1 is running" },
    { "label": "Database reachable", "state": "pass", "detail": "MariaDB responded" }
  ],
  "suggestedFix": null
}
```

## `GET /api/audit`

Returns audit entries with filters for date range, service, action, and status.

## Data Sources

Likely backend collectors:

- Docker SDK or Docker CLI for container state, restart counts, and resource usage.
- `/proc/mdstat` and `mdadm --detail /dev/md0` for RAID health.
- `df` for `/mnt/data` capacity.
- `/var/log/server-backup.log` for quick and full backup state.
- `rclone about remote:bucket --json` for cloud backup usage.
- DNS probes against the configured `JARAD_DNS_SERVER`.
- Uptime Kuma API for monitor state if preferred.
