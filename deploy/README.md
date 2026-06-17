# Deployment

This folder contains server-side deployment templates.

## Systemd Services

- `jarad-backend.service`
  - Runs the FastAPI backend from `~/mobile/backend`.
  - Uses `~/mobile/backend/.venv/bin/uvicorn`.
  - Reads `~/mobile/backend/.env`.
  - Listens on `127.0.0.1:8443` by default.
  - Allows browser requests from localhost and the origins configured in `~/mobile/backend/.env`.

- `jarad-frontend.service`
  - Serves the static PWA from `~/mobile/frontend`.
  - Uses Python's built-in static server.
  - Listens on `127.0.0.1:5178` by default.

## Caddy Route

The Caddy route assumes Caddy is host-networked, uses the Tailscale certificate from `/var/lib/tailscale/certs`, and proxies localhost services. The default Caddyfile path is `~/caddy/Caddyfile`; override it with `--caddyfile` or `-Caddyfile` if needed.

For local machine-specific deploy values, copy one of these templates and keep the copy out of Git:

```bash
cp deploy/local.env.example deploy/local.env
cp deploy/local.ps1.example deploy/local.ps1
```

The Bash deploy script reads `deploy/local.env` automatically.

Install or update the route with:

```bash
bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user> --backend-only --install-caddy --caddy-domain <device.tailnet.ts.net>
```

PowerShell equivalent:

```powershell
.\scripts\deploy.ps1 -HostName <server-ip-or-host> -User <ssh-user> -BackendOnly -InstallCaddy -CaddyDomain <device.tailnet.ts.net>
```

Default public app URL shape:

```text
https://<device.tailnet.ts.net>:8444
```

The installed Caddy block is:

```caddyfile
<device.tailnet.ts.net>:8444 {
    tls /certs/<device.tailnet.ts.net>.crt /certs/<device.tailnet.ts.net>.key

    reverse_proxy /api/* localhost:8443
    reverse_proxy localhost:5178
}
```

The frontend and backend are same-origin through Caddy at that URL, so the mobile app can leave the FastAPI base URL blank and use `/api/*` automatically.

Install or update services from PowerShell with:

```powershell
.\scripts\deploy.ps1 -HostName <server-ip-or-host> -User <ssh-user> -InstallServices
```

After code changes, deploy and restart both:

```powershell
.\scripts\deploy.ps1 -HostName <server-ip-or-host> -User <ssh-user> -RestartServices
```

Bash equivalent:

```bash
bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user> --restart-services
```

Check service status on the server:

```bash
sudo systemctl status jarad-backend.service
sudo systemctl status jarad-frontend.service
```

View logs:

```bash
journalctl -u jarad-backend.service -f
journalctl -u jarad-frontend.service -f
```

If the browser reports a CORS error, confirm the frontend origin is allowed. For a strict setup, add the deployed frontend origin to `~/mobile/backend/.env`:

```bash
JARAD_ALLOWED_ORIGINS=http://<server-lan-ip>:5178,https://<device.tailnet.ts.net>:8444
```

Then restart the backend:

```bash
sudo systemctl restart jarad-backend.service
```
