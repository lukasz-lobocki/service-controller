# Development Workflow

Step-by-step guide for running service-controller on a developer
machine without breaking production configurations.

> **TL;DR** — Python 3.9+, venv with Flask, set `SERVICES_CONFIG`,
> `SYSTEMD_SERVICES`, or `SYSTEMD_SERVICE` to wire up test units, then
> `python app.py`. Never run the dev instance as `root`.

---

## Table of contents

1. [Development installation](#1-development-installation)
2. [Configuring services](#2-configuring-services)
3. [Running Flask in development](#3-running-flask-in-development)
4. [Testing the API with curl](#4-testing-the-api-with-curl)
5. [Testing sudoers with `sudo -l`](#5-testing-sudoers-with-sudo--l)
6. [Adding test services](#6-adding-test-services)
7. [Verifying everything is wired up](#7-verifying-everything-is-wired-up)
8. [Development Caddy reverse proxy](#8-development-caddy-reverse-proxy)
9. [Tips and gotchas](#9-tips-and-gotchas)

---

## 1. Development installation

### 1.1 System requirements

| Requirement | Minimum | Notes |
|---|---|---|
| Python | 3.9 | Required for `re.fullmatch` pattern support in `services.py` |
| systemd | any | For testing real units; optional if you use a fake unit |
| sudo | any | For testing the sudoers rule |
| Caddy | any | Optional — only required for reverse proxy testing |

### 1.2 Create a venv

```bash
cd /home/la_lukasz/Code/service-controller
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install flask  # required package
```

`pip install -r requirements.txt` is not required because Flask is
the only external import (see `app.py` line 12).

### 1.3 Optional — install the development server

If you want to run directly out of the workspace tree instead of
`/opt/service-controller`:

```bash
source venv/bin/activate
python app.py
# or, to bind to LAN:
python -c "import app; app.run(host='127.0.0.1')"
```

Alternatively, `install.sh --dev` can help — it runs the install
script with `--no-deploy`, leaving you with the files in-place and a
working venv.

---

## 2. Configuring services

Three mechanisms, in order of precedence (see
`services.py:_raw_entries` lines 25–40):

1. **`SERVICES_CONFIG` env var** — points to any JSON file on disk.
   Override:

   ```bash
   export SERVICES_CONFIG=/tmp/my-services.json
   python app.py
   ```

2. **`SYSTEMD_SERVICES` env var** — comma-separated unit names,
   overrides file-based config. Useful for one-off tests:

   ```bash
   export SYSTEMD_SERVICES="ssh.service,dhcpd.service"
   python app.py
   ```

3. **`SYSTEMD_SERVICE` env var** (singular) — legacy single-service
   mode.

4. **Fallback default** — `llama-server.service` if none of the
   above is set.

> **Important**: unit names must end in `.service` and match the
> regex `^[A-Za-z0-9@_.\-]+\.service$` (see `services.py` line 23).
> Invalid names fail loudly at startup rather than silently dying
> later.

### 2.1 JSON file layout

```json
[
  {
    "unit": "livedisk.service",
    "id": "livedisk",
    "label": "Live Disk Writer"
  }
]
```

- `unit` — required, the exact unit name.
- `id` — required if not derivable from unit name; must match
  `^[a-z0-9][a-z0-9-]*$`.
- `label` — optional; auto-generated title-cased slug if missing.

---

## 3. Running Flask in development

The development Flask server is intentionally different from
production:

- **Listening on `127.0.0.1:8090`** — not `0.0.0.0`.
- **NOT hardened** — no systemd drop-ins, no Caddy in front.
- **Hot-reload on** — edits to `app.py` or `templates/` take effect
  without restart.

```bash
# Activate venv first (if using the development layout)
source venv/bin/activate

# Run in development
python app.py

# Output:
#  * Serving Flask app "app"
#  * Running on http://127.0.0.1:8090/ (Press CTRL+C to quit)
```

To override:

```bash
export PORT=9090 HOST=127.0.0.1
python app.py -v   # verbose
```

---

## 4. Testing the API with curl

### 4.1 GET /api/services

```bash
curl -s http://127.0.0.1:8090/api/services | python3 -m json.tool
# [
#   {
#     "id": "livedisk",
#     "unit": "livedisk.service",
#     "label": "Live Disk Writer"
#   },
#   ...
# ]
```

### 4.2 GET /api/status — all services

```bash
curl -s http://127.0.0.1:8090/api/status | python3 -m json.tool
# {
#   "livedisk": {
#     "unit": "livedisk.service",
#     "active_state": "inactive",
#     "sub_state": "dead",
#     "enabled_state": "enabled",
#     "main_pid": "0",
#     "since": "",
#     "is_active": false,
#     "is_failed": false,
#     "is_transitioning": false,
#     "ok": true,
#     "error": null
#   }
# }
```

### 4.3 GET /api/status/<id>

```bash
curl -s http://127.0.0.1:8090/api/status/livedisk | python3 -m json.tool
```

### 4.4 POST /api/<id>/start

```bash
curl -X POST http://127.0.0.1:8090/api/livedisk/start | python3 -m json.tool
# {
#   "ok": true,
#   "error": null,
#   "status": {
#     "unit": "livedisk.service",
#     ...
#   }
# }
```

### 4.5 POST /api/<id>/stop

```bash
curl -X POST http://127.0.0.1:8090/api/livedisk/stop | python3 -m json.tool
```

### 4.6 POST /api/<id>/restart

```bash
curl -X POST http://127.0.0.1:8090/api/livedisk/restart | python3 -m json.tool
```

### 4.7 Error cases

```bash
# Unknown service id
curl -sv http://127.0.0.1:8090/api/status/unknown-service 2>&1 | tail
# HTTP/1.1 404 NOT FOUND
# {"ok":false,"error":"unknown service id"}

# Unknown verb
curl -sx POST http://127.0.0.1:8090/api/livedisk/banana | python3 -m json.tool
# {"ok":false,"error":"unsupported action"}
```

---

## 5. Testing sudoers with `sudo -l`

### 5.1 Preview your sudoers policy

Before deploying to `/etc/sudoers.d/`, preview the rules for user
`service-controller`:

```bash
python3 scripts/gen_sudoers.py --user service-controller
```

Output:

```text
# sudoers — generated for 5 service(s)
Cmnd_Alias SVC_CTL_LLAMA_GPX = /usr/bin/systemctl start llama-gui.service,
    /usr/bin/systemctl stop llama-gui.service,
    /usr/bin/systemctl restart llama-gui.service
SVC_CTL_STABLEDIFF = /usr/bin/systemctl start stable-diffusion.service
    /usr/bin/systemctl stop stable-diffusion.service,
    /usr/bin/systemctl restart stable-diffusion.service

service-controller ALL=(root) NOPASSWD: SVC_CTL_LLAMA_GPX, SVC_CTL_STABLEDIFF
```

### 5.2 Validate with `visudo -c`

Always validate before installing:

```bash
python3 scripts/gen_sudoers.py > /tmp/test-sudoers
sudo visudo -c -f /tmp/test-sudoers
# /tmp/test-sudoers: parsed OK
```

### 5.3 Test using real sudo

Once the file is installed under `/etc/sudoers.d/`, verify the policy
matches what the user will see:

```bash
sudo -l -U service-controller | grep "NOPASSWD"
# service-controller can run the following commands on host:
#     (root) NOPASSWD: /usr/bin/systemctl start ...,
#                         /usr/bin/systemctl stop ...,
#                         /usr/bin/systemctl restart ...
```

### 5.4 Test a real run as the unprivileged user

```bash
sudo -u service-controller /usr/bin/sudo -n systemctl start livedisk.service
```

If `sudo: a password is required` — sudoers not installed or user
not allowed.

If `sudo: unknown user: service-controller` — the user doesn't exist
on this host.

---

## 6. Adding test services

### 6.1 Create a sleep.sh example

For simple testing, create a systemd service that sleeps for 60
seconds. This lets you see status transitions without installing real
services:

```bash
# 1. Create a systemd unit in /tmp/test-services/
mkdir -p /tmp/test-services

cat > /tmp/test-services/sleeper.service <<EOF
[Unit]
Description=Test sleeper
[Service]
ExecStart=/bin/sleep 60
[Install]
WantedBy=multi-user.target
EOF

# 2. Symlink into systemd
sudo ln -s /tmp/test-services/sleeper.service /etc/systemd/system/

# 3. Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable sleeper.service

# 4. Add to services.json
cat > /tmp/my-services.json <<EOF
[{"unit": "sleeper.service", "id": "sleeper", "label": "Test Sleeper"}]
EOF

export SERVICES_CONFIG=/tmp/my-services.json
python app.py
```

### 6.2 Interact via the web UI

Open [http://127.0.0.1:8090](http://127.0.0.1:8090) and verify:

- Panel shows "Sleeper".
- Status updates every 30s.
- Click "Start" → status becomes "active".
- Click "Stop" → status becomes "inactive".
- JSON output matches what you see in the UI.

### 6.3 Verify via /api

```bash
# Poll status
while true; do
    curl -s http://127.0.0.1:8090/api/status/sleeper
    echo
    sleep 2
done | python3 -m json.tool
```

---

## 7. Verifying everything is wired up

Final check list after editing `services.json`:

1. **service-controller.env** — verify all required env vars are set
   (see §2 of deployment-guide).
2. **sudoers file** — generated with `scripts/gen_sudoers.py` (see
   §3 of deployment-guide).
3. **Flask app** — running correctly.
4. **Reverse proxy** — if you want Caddy in front (see §5 of
   deployment-guide).

Test in order:

```bash
# 1. Confirm running services
sudo systemctl --no-pager list-units --type=service | grep <service-name>

# 2. Confirm services.json has the right entries
python3 -c "
import json
with open('services.json') as f:
    data = json.load(f)
    for s in data:
        print(s['id'], s['unit'], s.get('label', ''))
"

# 3. Confirm sudoers rule covers every configured service
python3 scripts/gen_sudoers.py | grep -q SVC_CTL_<id> && echo ok

# 4. Confirm the Flask backend is reachable
curl -s http://127.0.0.1:8090/api/status | python3 -m json.tool

# 5. Confirm reverse proxy can reach Flask (if you have one)
curl -s https://<your-domain>/api/status | python3 -m json.tool
```

---

## 8. Development Caddy reverse proxy

To test the Caddy reverse proxy, add this block to your Caddyfile:

```caddyfile
service-controller.example.com:80 {
    reverse_proxy localhost:8090
}
```

You can test the whole stack (Caddy + Flask):

1. Start Flask manually:

   ```bash
   python app.py
   ```

2. Start Caddy:

   ```bash
   caddy start
   ```

3. Test:

   ```bash
   curl -s http://service-controller.example.com:80/api/status
   ```

Adjust the port number (`80` rather than `443`) for simpler TLS-free
testing.

---

## 9. Tips and gotchas

### 9.1 Never use `sudo` to run development

If you accidentally run `app.py` as `root`, the sudoers rule will
never grant access — `all=(root)` already grants access to root, it
just doesn't grant access to `sudo` from root. This creates a
**loop**: you can't run sudo from root, and sudo expects you to be
root.

### 9.2 Don't use `--port` in development

You may be tempted to use `--port 0.0.0.0` for LAN testing. Either:

- Use Caddy as your reverse proxy (preferred for security), or
- Use `python -c "import app; app.run(host='0.0.0.0', port=8090)"`
  temporarily for local LAN testing.

Don't run `app.py --http 0.0.0.0:8090` in production.

### 9.3 Hot-reload disabled in production

Development mode: `python app.py` — hot-reload is on.

Production mode: `systemctl start service-controller.service` —
hot-reload is off.

### 9.4 Use `--user` flag for gen_sudoers

Always pass `--user service-controller` to `gen_sudoers.py`. If you
forget, the file won't be valid for any user.

```bash
python3 scripts/gen_sudoers.py --user service-controller
```

### 9.5 Re-generate sudoers AFTER editing services.json

Every time you modify `services.json`, run:

```bash
python3 scripts/gen_sudoers.py > /tmp/service-controller-sudoers
sudo cp /tmp/service-controller-sudoers /etc/sudoers.d/service-controller
```

Failure to do so means new services will show in the UI but won't
actually be controllable.
