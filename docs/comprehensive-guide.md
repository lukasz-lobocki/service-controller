# Service-Controller Comprehensive Guide

A single-page reference for the service-controller project. See also [README.md](../README.md), [architecture.md](architecture.md), [api-reference.md](api-reference.md), [security-model.md](security-model.md), [configuration-reference.md](config-reference.md), [deployment-guide.md](deployment-guide.md), [development-workflow.md](development-workflow.md), [css-reference.md](css-reference.md).

---

## 1. Architecture Overview

Service-controller is a single-page web UI deployed as a small Python Flask application that sits between the operator's browser and systemd. It polls systemctl for status every 5 seconds and issues sudo-wrapped `systemctl start/stop/restart` commands when the user clicks the buttons.

### 1.1 Component diagram

```
  Browser (HTTP/HTTPS)
    |
    v
[ Reverse proxy ]             Caddy + PocketID (recommended)
  or nginx / HTPC             or any auth-aware HTTP proxy
    |
    v
[ service-controller.service ]
  systemd | User=service-controller
  ExecStart=/opt/service-controller/venv/bin/python app.py
  Binds: 127.0.0.1:8090 (environment HOST/PORT)
    |
    ├── Flask app (app.py)
    |     GET  /api/status       -> systemctl show  (no sudo)
    |     GET  /api/services     -> in-memory list
    |     GET  /api/status/<id>  -> systemctl show  (no sudo)
    |     POST /api/<id>/<verb>  -> sudo systemctl (verb in {start, stop, restart})
    |
    ├── /opt/service-controller/services.json
    |     resolved by services.py (SERVICES_CONFIG > SYSTEMD_SERVICES > SYSTEMD_SERVICE > default)
    |
    └── /usr/bin/sudo (sudoers policy)
          /usr/bin/systemctl (sudoers-allowed verbs per unit)
```

### 1.2 File layout

```
/opt/service-controller/
├── app.py                           Flask app, 7 REST endpoints
├── services.py                      Service list loader and validator
├── services.json                    JSON config (edit to add/remove services)
├── scripts/gen_sudoers.py           Generates sudoers rule from services.json
├── service-controller.service       Systemd unit file (copied to /etc/systemd/system/)
├── templates/index.html             Jinja template: one panel per service
├── static/
│   ├── app.js                       Vanilla JS — panels, polling, actions
│   ├── style.css                    UI styling with LED panels
│   └── favicon.svg                  3-dot favicon
└── venv/                            Python venv (created by install)
    └── bin/python                   Flask runs here
```

### 1.3 Key design principles

- **Config-only access surface**: service IDs come exclusively from server-side config (`services.json` or env vars); the URL path parameter is always resolved against that allow-list.
- **No shell injection**: `subprocess.run()` is invoked with a list argv, never with `shell=True`. Unit names come from validated config only.
- **sudoers pinning**: exactly one sudoers rule per configured unit, generated via `gen_sudoers.py` so the rule can never drift from the UI.
- **Loose coupling with systemd**: the backend is a one-trick pony: `systemctl show` for status and `sudo systemctl <verb>` for actions.

---

## 2. Configuration Options

### 2.1 Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `HOST` | `127.0.0.1` | Flask bind address — keep `127.0.0.1`, never `0.0.0.0` in production. |
| `PORT` | `8090` | Flask port — reverse proxy forwards to this port. |
| `SERVICES_CONFIG` | `./services.json` relative to project root | Path to JSON config file listing managed services. |
| `SYSTEMD_SERVICES` | _(none)_ | Comma-separated list of unit names; takes precedence over `SERVICES_CONFIG`. |
| `SYSTEMD_SERVICE` | _(none)_ | Single unit name (legacy only); takes precedence only when `SYSTEMD_SERVICES` is unset. |

Precedence order is exactly: `SYSTEMD_SERVICES` > `SYSTEMD_SERVICE` > file at `SERVICES_CONFIG` (or `services.json`) > fallback default `llama-server.service`.

### 2.2 `services.json` schema

```json
[
  {
    "unit": "str",      // required. Systemd unit name; must match UNIT_RE.
    "id":   "str?",     // optional — auto-derived slug if omitted
    "label":"str?"      // optional — auto-derived title if omitted
  },
  ...
]
```

Rules (see `services.py`):

- `unit` must match `^[A-Za-z0-9@_.\-]+\.service$`.
- `id` is auto-derived from the unit name by `_slugify()`: strip `.service` suffix, lowercase, replace non-alphanumeric with `-`, collapse runs, strip leading/trailing dashes. Must additionally match `^[a-z0-9][a-z0-9-]*$`.
- `label` is auto-derived from the id by `_titleize()`: split on `-`, capitalize each word, join with spaces.

Duplicate `id` values are rejected at startup with `ServiceConfigError`.

### 2.3 Validation failures

Invalid unit names or malformed JSON → `ServiceConfigError` → app prints `service-controller config error: ...` and exits; systemd restarts the dying process (per `Restart=on-failure` in `service-controller.service`), but each restart will die on the same bad config. A config typo is therefore a loud fail, not a silent one.

---

## 3. Service Management

### 3.1 Systemctl integration

Two code paths in `app.py`:

| Path | sudo? | Command | Purpose |
|---|---|---|---|
| `get_status(unit)` | No | `/usr/bin/systemctl show <unit> -p ActiveState,SubState,UnitFileState,MainPID,ExecMainStartTimestamp` | Read-only status polling every ~5 s. |
| `run_systemctl([verb, unit], use_sudo=True)` | Yes | `/usr/bin/sudo /usr/bin/systemctl <verb> <unit>` | start / stop / restart. |

`ALLOWED_VERBS = {"start", "stop", "restart"}` (line 41 in `app.py`). Anything else is rejected with `{"ok": false, "error": "unsupported action"}` before sudo is invoked.

`STATUS_FIELDS = "ActiveState,SubState,UnitFileState,MainPID,ExecMainStartTimestamp"` (line 42 of `app.py`).

### 3.2 Sudoers configuration

`scripts/gen_sudoers.py` reads the common `services.py` loader and emits one `Cmnd_Alias` per configured service:

```
# service-controller sudoers — generated for 2 service(s)

Cmnd_Alias SVC_CTL_LAMA_SERVER = /usr/bin/systemctl start llama-server.service, /usr/bin/systemctl stop llama-server.service, /usr/bin/systemctl restart llama-server.service
Cmnd_Alias SVC_CTL_STABLEDIFF = /usr/bin/systemctl start stable-diffusion.service, /usr/bin/systemctl stop stable-diffusion.service, /usr/bin/systemctl restart stable-diffusion.service

service-controller ALL=(root) NOPASSWD: SVC_CTL_LAMA_SERVER, SVC_CTL_STABLEDIFF
```

Install:

```bash
cd /opt/service-controller
python3 scripts/gen_sudoers.py --user service-controller > /tmp/service-controller-sudoers
sudo visudo -c -f /tmp/service-controller-sudoers   # validate first
sudo cp /tmp/service-controller-sudoers /etc/sudoers.d/service-controller
```

Always re-generate and reinstall when `services.json` changes — otherwise newly added services will be controllable from the UI but the actual `systemctl` calls will fail with sudo permission errors.

### 3.3 Adding a service

1. Edit `services.json` (or the path pointed to by `SERVICES_CONFIG`).
2. Re-run `gen_sudoers.py` and reinstall the sudoers rule.
3. `sudo systemctl restart service-controller.service`.

No code changes needed — the UI is populated entirely from the config list.

---

## 4. API Reference

All routes live in `app.py`.

| Route | Method | Response | Notes |
|---|---|---|---|
| `/` | GET | HTML (Jinja template `templates/index.html`) | Service list embedded as `window.__SERVICES__` (Jinja `{{ services|tojson }}`). |
| `/api/services` | GET | JSON `[{id, unit, label}, ...]` | Returns the allow-listed services currently loaded. |
| `/api/status` | GET | JSON `{id: status, ...}` | One round-trip regardless of service count. |
| `/api/status/<service_id>` | GET | JSON single service | 404 if not in allow-list. |
| `/api/<service_id>/start` | POST | JSON with `new_status` | Action for one service. |
| `/api/<service_id>/stop` | POST | JSON with `new_status` | Action for one service. |
| `/api/<service_id>/restart` | POST | JSON with `new_status` | Action for one service. |

### 4.1 `GET /api/services`

```json
[
  {"id": "llama-gpu-strixhalo", "unit": "llama-cpp-strixhalo.service", "label": "StrixHalo llama Ornith (GPU)"}
]
```

### 4.2 `GET /api/status/<id>`

```json
{
  "unit": "llama-cpp-strixhalo.service",
  "active_state": "active",
  "sub_state": "running",
  "enabled_state": "enabled",
  "main_pid": "12345",
  "since": "Aug 8, 14:02:34",
  "is_active": true,
  "is_failed": false,
  "is_transitioning": false,
  "ok": true,
  "error": null
}
```

Status field mapping: each field comes straight out of `systemctl show ... -p` output, parsed as `Key=Value`, then lowered. Derived booleans use simple string-equality checks against `active_state`; `ok` is True iff exit code was 0.

### 4.3 `POST /api/<id>/stop` (same for `start`, `restart`)

```json
{
  "ok": true,
  "error": null,
  "new_status": { ... same shape as GET /api/status/<id> ... }
}
```

### 4.4 Error cases

- Unknown id: returns 404 with `{"ok": false, "error": "unknown service id"}`.
- Unsupported verb: returns 400 with `{"ok": false, "error": "unsupported action"}`.
- Subprocess timeout (15 s hard cap): returns `{"ok": false, "error": "<timeout message>"}`.
- Missing sudo/systemctl binary: same shape, same `ok: false`.

### 4.5 curl examples

```bash
# Read status for one service
curl -s http://127.0.0.1:8090/api/status/llama-gpu-l | python -m json.tool

# Start a service
curl -s -X POST http://127.0.0.1:8090/api/llama-gpu-l/start | python -m json.tool

# Try an unknown id (404)
curl -sv http://127.0.0.1:8090/api/status/never-heard-of-it 2>&1 | tail
# HTTP/1.1 404
# {"ok": false, "error": "unknown service id"}
```

---

## 5. Security Model

### 5.1 Authentication

No auth built into the app — reverse proxy is responsible.

| Layer | Where it lives | Notes |
|---|---|---|
| Network binding | `127.0.0.1` only by default (env `HOST`) | Don't bind to `0.0.0.0`. Anyone on your LAN can start/stop services. |
| Auth | Caddy + PocketID forward_auth (recommended) or any auth-aware HTTP proxy. | The proxy decides who can reach the UI. |
| Auth bypass | None — if someone bypasses the proxy they can stop services. | This is a design choice; you explicitly opt-out by binding to `0.0.0.0` or opening the Flask port on the network. |

### 5.2 Caddy + PocketID forward_auth

Recommended production pattern:

```
service-controller.example.com {
    forward_auth login.example.com {
        uri /api/verify
        copy_headers Remote-User Remote-Email
    }
    reverse_proxy 127.0.0.1:8090
}
```

### 5.3 Threat model

| Threat | Defence | Code location |
|---|---|---|
| Unit-name injection via URL | IDs are looked up against a server-side allow-list; unknown ids => 404. | `app.py` `_api_action` |
| Subprocess injection (shell metacharacters) | `subprocess.run()` with list argv; no `shell=True`. Unit names come from validated config only. | `app.py` `run_systemctl` |
| Config typos reaching sudo | Unit names validated with `UNIT_RE` at load time; invalid unit fails startup. | `services.py` `_validate_unit` |
| Mis-matched sudoers and config | `gen_sudoers.py` reads `services.py`; you must re-run on edits. | `scripts/gen_sudoers.py` |
| Out-of-band access to systemctl binaries | sudoers grants exactly three commands per unit; adding a unit requires sudoers update. | Generated rules |

### 5.4 Hardening checklist

- [ ] Generated and validated sudoers (`visudo -c -f`).
- [ ] Install under `/etc/sudoers.d/` with `0440 root:root`.
- [ ] Run app as unprivileged user `service-controller` via systemd `User=` directive.
- [ ] Reverse proxy configured with auth (Caddy+PocketID recommended).
- [ ] Caddy server enforces TLS.
- [ ] Optionally wrap `sudo` invocation with `auditd`.

---

## 6. Reverse Proxy Setup

### 6.1 Basic Caddy setup

```
service-controller.example.com {
    forward_auth login.example.com {
        uri /api/verify
        copy_headers Remote-User Remote-Email
    }
    reverse_proxy 127.0.0.1:8090
}
```

Caddy auto-issues TLS; change `service-controller.example.com` to your real domain.

### 6.2 Caddy over LAN (no auth, IP allow-list)

```
service-controller.example.com {
    respond "forbidden" 403 {
        @public ip 10.0.0.0/8 192.168.0.0/16 172.16.0.0/12
    }
    reverse_proxy 127.0.0.1:8090
}
```

### 6.3 Nginx basic auth alternative

If you don't want Caddy/PocketID, nginx basic auth is fine too:

```nginx
server {
    listen 443 ssl;
    server_name service-controller.example.com;
    ssl_certificate /etc/letsencrypt/live/service-controller.example.com/cert.pem;
    ssl_certificate_key /etc/letsencrypt/live/service-controller.example.com/privkey.pem;

    location / {
        auth_basic "Service Controller";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass              http://127.0.0.1:8090;
        proxy_set_header Host   $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 6.4 Don't bind Flask directly

The default bind address is `127.0.0.1` — not `0.0.0.0`. Anyone on your LAN can reach services if you bind to `0.0.0.0`. Caddy handles TLS and auth.

---

## 7. Development Workflow

### 7.1 Local venv setup

Prerequisites: Python 3.9+, systemd (for testing fake units). Skip Caddy unless you want to test reverse proxy.

```bash
cd /home/la_lukasz/Code/service-controller
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install flask
```

### 7.2 Running the dev server

```bash
source venv/bin/activate
python app.py
# Output:
#  * Serving Flask app "app"
#  * Running on http://127.0.0.1:8090/ (Press CTRL+C to quit)
```

Open http://127.0.0.1:8090 in a browser.

### 7.3 Creating test services

Test with a fake sleep-based service:

```bash
# 1. Create a systemd unit in /tmp/test-services/
mkdir -p /tmp/test-services
cat > /tmp/test-services/sleeper.service << EOF
[Unit]
Description=Test sleeper
[Service]
ExecStart=/bin/sleep 60
[Install]
WantedBy=multi-user.target
EOF

# 2. Symlink into systemd
sudo ln -s /tmp/test-services/sleeper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sleeper.service

# 3. Add to services.json
cat > /tmp/my-services.json << EOF
{"unit": "sleeper.service", "id": "sleeper", "label": "Test Sleeper"}
]
EOF

export SERVICES_CONFIG=/tmp/my-services.json
python app.py
```

### 7.4 Testing the API with curl

```bash
# List services
curl -s http://127.0.0.1:8090/api/services | python3 -m json.tool

# Bulk status
curl -s http://127.0.0.1:8090/api/status | python3 -m json.tool

# Single status
curl -s http://127.0.0.1:8090/api/status/sleeper | python3 -m json.tool

# Start action
curl -s -X POST http://127.0.0.1:8090/api/sleeper/start | python3 -m json.tool

# Stop action
curl -s -X POST http://127.0.0.1:8090/api/sleeper/stop | python3 -m json.tool
```

### 7.5 Development Caddy reverse proxy

For HTTPS in development:

```
service-controller.example.com:80 {
    reverse_proxy localhost:8090
}
```

Test flow:

1. Start Flask manually: `python app.py`
2. Start Caddy: `caddy start`
3. Test: `curl -s http://service-controller.example.com:80/api/status`

---

## 8. Production Deployment

### 8.1 Install steps

1. Install unprivileged user:

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin service-controller
```

2. Copy files and create venv:

```bash
sudo mkdir -p /opt/service-controller
sudo cp -r app.py services.py services.json templates static scripts /opt/service-controller/
cd /opt/service-controller
sudo python3 -m venv venv
sudo ./venv/bin/pip install flask
sudo chown -R service-controller:service-controller /opt/service-controller
```

3. Generate and install sudoers:

```bash
cd /opt/service-controller
python3 scripts/gen_sudoers.py --user service-controller > /tmp/service-controller-sudoers
sudo visudo -c -f /tmp/service-controller-sudoers
sudo cp /tmp/service-controller-sudoers /etc/sudoers.d/service-controller
```

4. Enable the systemd unit:

```bash
sudo cp service-controller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now service-controller.service
```

### 8.2 systemd hardening

Edit `service-controller.service` (copy to `/etc/systemd/system/` first) with hardening directives:

```ini
[Service]
CapabilityBoundingSet=
AmbientCapabilities=

ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
ReadWritePaths=/opt/service-controller

PrivateTmp=yes
PrivateDevices=yes
PrivateNetwork=no  # Keep no so Flask can bind to localhost

SystemCallArchitectures=native
SystemCallFilter=@system-service
```

Restart after editing.

### 8.3 Caddy + PocketID for production

Replace `example.com` with your domain:

```
service-controller.example.com {
    forward_auth login.example.com {
        uri /api/verify
        copy_headers Remote-User Remote-Email
    }
    reverse_proxy 127.0.0.1:8090
}
```

### 8.4 Verifying the service ran

```bash
# Check it's active
sudo systemctl status service-controller.service

# Live log tail
sudo journalctl -eu service-controller.service --follow
```

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Panel stays on — state (inactive forever) | systemd unit is `dead` or `failed` — not just inactive. | `sudo systemctl status <unit>`, check journal. |
| Error banner: "lost contact with backend" | Flask app unreachable. | `systemctl status service-controller.service`, check `ss -tlnp | grep 8090`. |
| Service starts but buttons disabled | Sudo log shows permission denied. | `sudo journalctl | grep "sudo: service-controller"`. Ensure `visudo -c -f` passes. |
| Sudoers errors after config changes | sudoers not regenerated or not installed. | Re-run `gen_sudoers.py`, `visudo -c -f`, `cp`, `systemctl restart`. |
| Service won't start because `sudo: unknown user: service-controller` | User the sudoers rule grants access to must exist before the app runs. | Re-generate sudoers with the correct `--user` flag, or fix the `User=` directive. |
| Caddy won't reach Flask | Wrong `reverse_proxy` destination (must be `http://127.0.0.1:8090`). | Update Caddyfile to match flask's `HOST`/`PORT` values. |
| Flask port is open on LAN | Flask is bound to `0.0.0.0` instead of `127.0.0.1`. | Check `HOST` env var in `service-controller.service`. |
| Panel starts/stops/refreshes oddly | "lost contact" error — Flask not reachable. | Confirm Flask is running and reachable. |
| systemd restart loops | Config failed validation at startup (ServiceConfigError). | Check journal for `service-controller config error: ...`. |

### Sudoers reinstall procedure

Edit `services.json`. Re-generate and reinstall sudoers:

```bash
cd /opt/service-controller
python3 scripts/gen_sudoers.py --user service-controller > /tmp/service-controller-sudoers
sudo visudo -c -f /tmp/service-controller-sudoers
sudo cp /tmp/service-controller-sudoers /etc/sudoers.d/service-controller
sudo systemctl restart service-controller.service
```

### Verify the install

```bash
# Confirm config loaded
python3 -c "
import json
with open('services.json') as f:
    data = json.load(f)
    for s in data:
        print(s['id'], s['unit'], s.get('label', ''))
"

# Confirm Flask backend is reachable
curl -s http://127.0.0.1:8090/api/status | python3 -m json.tool

# Confirm reverse proxy can reach Flask (if you have one)
curl -s https://<your-domain>/api/status | python3 -m json.tool
```

---

## Appendix

### A. Checklist for adding a new service

1. Add to `services.json`.
2. Re-generate and reinstall sudoers.
3. `sudo systemctl restart service-controller.service`.

### B. Sudo policy file location

`/etc/sudoers.d/service-controller` (generated by `gen_sudoers.py`). Validate with `sudo visudo -c -f <file>` before installing.

### C. Sudoers alias naming

Cmnd_Alias name: `SVC_CTL_<id>` where `id` is the service id, uppercased, with `-` replaced by `_`. Same logic as `gen_sudoers.py`.

### D. Environment variable overrides

- `HOST` — change bind address (NOT recommended in production).
- `PORT` — change port (default `8090`).
- `SERVICES_CONFIG` — point to a custom JSON file instead of `services.json`.
- `SYSTEMD_SERVICES` — comma-separated unit lists (no `services.json` file needed).
- `SYSTEMD_SERVICE` — single-unit legacy support.

### E. Key file paths every operator should know

| Path | Purpose |
|---|---|
| `/opt/service-controller/services.json` | Service allow-list |
| `/opt/service-controller/service-controller.service` | Systemd unit file (local copy) |
| `/etc/systemd/system/service-controller.service` | The live unit (copy of above) |
| `/etc/sudoers.d/service-controller` | Sudoers policy generated by `gen_sudoers.py` |
| `/var/log/syslog` or `journalctl` | sudoer and Flask logs respectively |
| `/etc/caddy/Caddyfile` or `/etc/caddy/Caddyfile` | Reverse proxy config (varies by distribution) |

### F. Common commands

```bash
# Tail logs of the Flask app
sudo journalctl -eu service-controller.service --follow

# Restart (e.g. after adding a service)
sudo systemctl restart service-controller.service

# Show live log (Flask app)
sudo systemctl status service-controller.service

# Stop systemd service
sudo systemctl stop service-controller.service

# Remove the sudoers policy and reinstall it
sudo rm /etc/sudoers.d/service-controller
sudo visudo -c -f /tmp/service-controller-sudoers
sudo cp /tmp/service-controller-sudoers /etc/sudoers.d/service-controller

# Check Flask is bound
ss -tlnp | grep 8090
```
