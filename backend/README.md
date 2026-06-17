# Jarad Backend

FastAPI backend for the Jarad mobile PWA. It is designed to run on a private network or behind an authenticated HTTPS proxy.

## What It Provides

- `GET /api/mobile/state`
  - Server metrics
  - Storage and RAID summary
  - Backup summary
  - Docker service state
  - Alerts, logs, and network status
- `GET /api/services/{service_id}/logs`
- `GET /api/services/{service_id}/diagnostics`
- `POST /api/admin/actions/{action_id}`
  - Only whitelisted `start-{service_id}`, `restart-{service_id}`, and `stop-{service_id}` actions
  - Protected actions require fingerprint confirmation from the PWA or a valid backend-verified TOTP code
  - No arbitrary shell command endpoint

## Package Layout

- `jarad_backend/main.py` - FastAPI app assembly, CORS, and router registration.
- `jarad_backend/routes.py` - HTTP endpoints and response composition.
- `jarad_backend/config.py` - `.env` loading, public host settings, allowed origins, and service catalog.
- `jarad_backend/auth.py` - bearer token, TOTP, and protected-action authorization.
- `jarad_backend/metrics.py` - host uptime, CPU, RAM, temperature, disk, RAID, and backup-log readers.
- `jarad_backend/docker.py` - Docker CLI wrappers and parsers.
- `jarad_backend/services.py` - service health aggregation, diagnostics, network state, logs, and alerts.
- `jarad_backend/models.py` - Pydantic request models.
- `jarad_backend/command.py` - bounded subprocess helper.

## Local Development

Create a virtual environment:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On Windows, use Python 3.12 if the default `python` points to 3.14:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Run:

```bash
uvicorn jarad_backend.main:app --host 127.0.0.1 --port 8443 --reload
```

For local testing, set a real token in `backend/.env` or explicitly allow the placeholder:

```bash
JARAD_APP_TOKEN=change-this-long-random-token
JARAD_ALLOW_INSECURE_DEFAULTS=1
```

In the PWA settings, use:

```text
FastAPI base URL: http://127.0.0.1:8443
Access token: <JARAD_APP_TOKEN>
```

## Server Deployment

On the server:

```bash
cd ~/mobile/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
nano .env
```

Set a long random `JARAD_APP_TOKEN` and a base32 `JARAD_TOTP_SECRET`. The backend refuses to start if `JARAD_APP_TOKEN` is missing or still set to the placeholder without `JARAD_ALLOW_INSECURE_DEFAULTS=1`.

Generate a TOTP secret:

```bash
python3 -c "import base64, secrets; print(base64.b32encode(secrets.token_bytes(20)).decode().rstrip('='))"
```

Add that secret to `.env`, then add the same secret manually to your authenticator app.
In Authy, add the generated value only, not the `JARAD_TOTP_SECRET=` prefix.

Run manually first from `~/mobile/backend`:

```bash
uvicorn jarad_backend.main:app --host 127.0.0.1 --port 8443
```

The backend reads `.env` from the current working directory at startup.
After changing `.env`, restart Uvicorn.

To check a TOTP code without running a Docker action:

```bash
curl -X POST http://127.0.0.1:8443/api/auth/totp/check \
  -H "Authorization: Bearer <JARAD_APP_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"code":"123456"}'
```

Recommended production binding is private-network-only, for example:

```bash
uvicorn jarad_backend.main:app --host 100.x.x.x --port 8443
```

Then enter this in the PWA:

```text
FastAPI base URL: http://100.x.x.x:8443
Access token: <JARAD_APP_TOKEN>
```

If Caddy proxies the backend, use the Caddy HTTPS URL instead.

## Security Notes

- Keep this backend on a private network or behind an authenticated HTTPS proxy.
- Do not port-forward it.
- Keep `JARAD_APP_TOKEN` out of Git.
- Keep `JARAD_TOTP_SECRET` out of Git.
- TOTP is verified by the backend before Docker actions run.
- Fingerprint/passkey prompts require HTTPS or localhost in modern browsers.
- Docker actions are intentionally whitelisted.
- The backend does not expose `/exec`, `/cmd`, `/shell`, or arbitrary command execution.
