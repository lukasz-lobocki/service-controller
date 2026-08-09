# service-controller

This repository is **AI-GENERATED**

A web page that shows the live status of a set of systemd services
and lets you start / stop / restart each one independently. One
panel per service, polling in parallel:

```
Service-Controller
2 units under management

┌──────────────────────────────┐  ┌──────────────────────────────┐
│ ● Llama Server (GPU)  ACTIVE │  │ ○ Stable Diffusion  INACTIVE │
│ llama-server.service         │  │ stable-diffusion.service     │
│ SubState        running      │  │ SubState        dead         │
│ UnitFileState    enabled     │  │ UnitFileState    enabled     │
│ MainPID          48213       │  │ MainPID          —           │
│ Since            Aug 8,14:02 │  │ Since            —           │
│ [ Stop ]   [ Restart ]       │  │ [ Start ]  [ Restart ]       │
└──────────────────────────────┘  └──────────────────────────────┘
```

## How it works

- `services.py` — loads and validates the list of controllable
  services (see Configuration below). Shared by the app and the
  sudoers generator so they can never drift apart.
- `app.py` — Flask backend. Reads status with `systemctl show`;
  start/stop/restart go through `sudo systemctl <verb> <unit>`.
  Requests reference a service only by its short `id` — the actual
  unit name never comes from a request, only from server-side config.
- `templates/` + `static/` — one panel per service, cloned from a
  `<template>` and populated from the embedded service list. A single
  bulk poll (`GET /api/status`) refreshes every panel each interval,
  regardless of how many services are configured.
- `scripts/gen_sudoers.py` — reads the same config as the app and
  prints the sudoers rule for it, so adding a service doesn't mean
  hand-editing sudoers syntax.

## Configuration

Services come from, in order of precedence:

1. **`services.json`** (or a path set via `SERVICES_CONFIG`) — a JSON
   list of `{"unit": "...", "id": "...", "label": "..."}`. Only
   `unit` is required; `id` and `label` are derived from it if
   omitted (`paperless-gpt.service` → id `paperless-gpt`, label
   `Paperless Gpt`).
2. **`SYSTEMD_SERVICES`** env var — comma-separated unit names, no
   file needed, for simple setups.
3. **`SYSTEMD_SERVICE`** env var (singular) — kept for backward
   compatibility with the original one-service version.
4. Fallback default: just `llama-server.service`.

`services.example.json` shows the JSON form with a few placeholder
units — copy it to `services.json` and edit in your real unit names:

```bash
cp services.example.json services.json
$EDITOR services.json
```

Every unit name is validated at startup (must look like
`some-name.service`) — a typo fails loudly instead of quietly
breaking start/stop later.

## 1. Install

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin service-controller
sudo mkdir -p /opt/service-controller
sudo cp -r app.py services.py services.json templates static scripts /opt/service-controller/
cd /opt/service-controller
sudo python3 -m venv venv
sudo ./venv/bin/pip install flask
sudo chown -R service-controller:service-controller /opt/service-controller
```

## 2. Scope sudo access

Generate the sudoers rule from your actual config instead of writing
it by hand — this keeps it in sync as you add or remove services:

```bash
cd /opt/service-controller
python3 scripts/gen_sudoers.py --user service-controller > /tmp/service-controller-sudoers
sudo visudo -c -f /tmp/service-controller-sudoers   # validate before installing
sudo cp /tmp/service-controller-sudoers /etc/sudoers.d/service-controller
```

Re-run this and reinstall whenever `services.json` changes — the
sudoers file and the app's service list must always match, or
start/stop for a newly added service will fail with a permission
error even though the app itself can see and display its status fine
(status reads need no privilege at all).

## 3. Run it as a systemd unit

```bash
sudo cp service-controller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now service-controller.service
```

Binds to `127.0.0.1:8090` by default — not reachable on the LAN until
you put something in front of it.

## 4. Put auth in front of it

No login of its own. Reusing the same Caddy + PocketID forward-auth
pattern already used for `llama-api.ideant.pl`:

```
service-controller.ideant.pl {
    forward_auth login.ideant.pl {
        uri /api/verify
        copy_headers Remote-User Remote-Email
    }
    reverse_proxy hp-ai.lan:8090
}
```

One login wall in front of a page that can stop several services —
worth double-checking this matches your real PocketID Caddy config
before exposing it.

## API

| Route                          | Method | Notes                                      |
|---------------------------------|--------|---------------------------------------------|
| `/`                              | GET    | The panel page                              |
| `/api/services`                  | GET    | `[{id, unit, label}, ...]`                   |
| `/api/status`                    | GET    | `{id: status, ...}` for every service        |
| `/api/status/<id>`                | GET    | Status for one service                       |
| `/api/<id>/start\|stop\|restart`  | POST   | Action for one service                        |

If you're upgrading from the original single-service version: the
old `/api/status` (single object) and `/api/start` etc. are gone —
status is now keyed by id and actions are scoped under `/api/<id>/`.

## Adding or removing a service

1. Edit `services.json`.
2. Re-run `scripts/gen_sudoers.py` and reinstall the sudoers file.
3. `sudo systemctl restart service-controller.service`.

No code changes needed for either step — panels are generated from
config on every page load.
