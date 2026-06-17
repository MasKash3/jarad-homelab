# Jarad

Mobile-first PWA and FastAPI backend for monitoring and controlling Jarad, a private home server.

## Structure

- `frontend/` - static PWA files served by any static file server.
- `backend/` - FastAPI service that reads host metrics, Docker service state, logs, diagnostics, and protected service actions.
- `API_CONTRACT.md` - current API shape for frontend/backend integration.

## Local Frontend Preview

```bash
node dev-server.mjs
```

Open:

```text
http://127.0.0.1:5178
```

## Local Backend Preview

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn jarad_backend.main:app --host 127.0.0.1 --port 8443 --reload
```

Copy `backend/.env.example` to `backend/.env` before real use and replace every placeholder.

## Deploy From Windows Or Bash

The deploy scripts copy the current `frontend/` and `backend/` folders to a server over SSH/SCP.

Optional local deploy values can live in ignored files:

```bash
cp deploy/local.env.example deploy/local.env
```

For Bash, `scripts/deploy.sh` reads `deploy/local.env` automatically when it exists. PowerShell users can copy `deploy/local.ps1.example` to `deploy/local.ps1` and dot-source it before calling `scripts/deploy.ps1`.

PowerShell:

```powershell
.\scripts\deploy.ps1 -HostName <server-ip-or-host> -User <ssh-user>
```

Bash:

```bash
bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user>
```

If `deploy/local.env` is configured, the Bash command can be shortened:

```bash
bash scripts/deploy.sh --restart-services
```

Common PowerShell options:

```powershell
# First-time service install or reinstall
.\scripts\deploy.ps1 -HostName <server-ip-or-host> -User <ssh-user> -InstallServices

# Install/update the Tailscale Caddy route
.\scripts\deploy.ps1 -HostName <server-ip-or-host> -User <ssh-user> -BackendOnly -InstallCaddy -CaddyDomain <device.tailnet.ts.net>

# Deploy both frontend and backend, then restart both services
.\scripts\deploy.ps1 -HostName <server-ip-or-host> -User <ssh-user> -RestartServices

# Frontend only
.\scripts\deploy.ps1 -HostName <server-ip-or-host> -User <ssh-user> -FrontendOnly -RestartFrontend

# Backend only
.\scripts\deploy.ps1 -HostName <server-ip-or-host> -User <ssh-user> -BackendOnly -RestartBackend

# Backend deploy, install dependencies, and restart systemd service
.\scripts\deploy.ps1 -HostName <server-ip-or-host> -User <ssh-user> -BackendOnly -InstallBackendDeps -RestartBackend
```

Common Bash options:

```bash
# First-time service install or reinstall
bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user> --install-services

# Install/update the Tailscale Caddy route
bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user> --backend-only --install-caddy --caddy-domain <device.tailnet.ts.net>

# Deploy both frontend and backend, then restart both services
bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user> --restart-services

# Frontend only
bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user> --frontend-only --restart-frontend

# Backend only
bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user> --backend-only --restart-backend

# Backend deploy, install dependencies, and restart systemd service
bash scripts/deploy.sh --host <server-ip-or-host> --user <ssh-user> --backend-only --install-backend-deps --restart-backend
```

Defaults:

- Remote root: `~/mobile`
- Frontend target: `~/mobile/frontend`
- Backend target: `~/mobile/backend`
- Frontend service: `jarad-frontend.service`
- Backend service: `jarad-backend.service`
- Frontend command: `python3 -m http.server 5178 --bind 127.0.0.1`
- Backend command: `uvicorn jarad_backend.main:app --host 127.0.0.1 --port 8443`
- Caddy app URL: `https://<device.tailnet.ts.net>:8444`

With Caddy installed, open the app through Tailscale:

```text
https://<device.tailnet.ts.net>:8444
```

When the app is opened from that HTTPS Tailscale URL, the backend URL can be left blank in settings. The frontend automatically uses the same origin and Caddy proxies `/api/*` to the backend.

The first service install copies templated systemd units to the server and runs:

```bash
sudo systemctl enable --now jarad-backend.service
sudo systemctl enable --now jarad-frontend.service
```

Later deploys use:

```bash
sudo systemctl restart jarad-backend.service jarad-frontend.service
```

`sudo` may prompt for your SSH password unless you configure passwordless access for those two service commands.

## Security

Do not expose the backend directly to the public internet. Run it on a private network or behind an authenticated HTTPS reverse proxy. Keep `.env`, access tokens, and TOTP secrets out of Git.
