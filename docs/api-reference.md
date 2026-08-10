# Service-Controller API Reference

> Source: `/home/la_lukasz/Code/service-controller/app.py`, `/home/la_lukasz/Code/service-controller/services.py`.

The application exposes four HTTP endpoints. This is a JSON REST API intended for use by the bundled single-page UI on `/`; all production users will want to call these endpoints from their own frontend (e.g. the `app.js` client in `static/app.js`, polling `/api/status` every 5 seconds).

A note on defaults:

* **Host bound by default:** `127.0.0.1` (loopback only) — configurable via the `HOST` environment variable. See `app.py` [lines 98–100].
* **Port:** configurable via the `PORT` environment variable, defaults to `8090`. See `app.py` [line 98].
* **No authentication or CSRF protection** is built in. The security model relies on placement behind an auth-aware reverse proxy rather than application-level auth. See `app.py` [docstring] and `docs/security-model.md`.

**Base URL:** `http://<host>:<port>` (typically `http://127.0.0.1:8090`).

---

## Content / Format

All endpoints under `/api/*` return **JSON** (`Content-Type: application/json`). The UI endpoint (`/`) returns HTML. There is no version prefix and no pagination. Requests generally take no body except HTTP method on `POST`. The app does not consume `Authorization` headers — they are the reverse proxy's responsibility.

---

## Endpoints

### `GET /`

Renders the single-page UI.

* **Auth:** none
* **Response body:** HTML document (`Content-Type: text/html`) referencing `index.html` from `templates/index.html`. Service metadata is embedded server-side as `window.__SERVICES__` for the client to consume.

```bash
curl http://127.0.0.1:8090/
# → HTML page…
```

The page pulls in `static/style.css` and `static/app.js`. `app.js` is the source of truth for the active client API calls: bulk `/api/status` polling every 5 000 ms and `POST /api/<id>/<verb>` for start/stop/restart.

---

### `GET /api/services`

Returns the allow-listed services currently loaded.

The service list is resolved through `services.load_services()` which reads from:

1. A JSON config file (path from `SERVICES_CONFIG` env var, or `services.json` next to `services.py` if that env var is unset). `services.py` [lines 35–44]
2. `SYSTEMD_SERVICES` env var — comma-separated unit names.
3. `SYSTEMD_SERVICE` env var (legacy, single service) — kept for backward compatibility.
4. Fallback default: `llama-server.service`.

* **Auth:** none
* **Response body:** JSON array of objects.

| Field    | Type   | Description                                          |
| -------- | ------ | ---------------------------------------------------- |
| `id`     | string | Slug identifier matching `^[a-z0-9][a-z0-9-]*$`     |
| `unit`   | string | Systemd unit name, e.g. `llama-server.service`      |
| `label`  | string | Human-readable label (auto-generated from slug or user-supplied) |

```bash
curl http://127.0.0.1:8090/api/services
# → [{"id":"llama-server","unit":"llama-server.service","label":"Llama-server"}]
```

---

### `GET /api/status`

Returns bulk status for **every** configured service in one response, keyed by service `id`.

* **Auth:** none
* **Response body:** JSON object `{[id]: {unit, active_state, sub_state, enabled_state, main_pid, since, is_active, is_failed, is_transitioning, ok, error}}`.

This is the primary polling endpoint. `static/app.js` uses it to refresh UI state for all services in one round trip.

| Field               | Type    | Description                                                                 |
| ------------------- | ------- | --------------------------------------------------------------------------- |
| `unit`              | string  | The systemd unit name                                                       |
| `active_state`      | string  | As reported by `systemctl show -p ActiveState`                              |
| `sub_state`         | string  | As reported by `systemctl show -p SubState`                                 |
| `enabled_state`     | string  | As reported by `systemctl show -p UnitFileState`                            |
| `main_pid`          | string  | As reported by `systemctl show -p MainPID`                                  |
| `since`             | string  | As reported by `systemctl show -p ExecMainStartTimestamp` (ISO-ish)         |
| `is_active`         | boolean | `true` if `active_state == "active"`                                        |
| `is_failed`         | boolean | `true` if `active_state == "failed"`                                        |
| `is_transitioning`  | boolean | `true` if `active_state` ∈ {`activating`, `deactivating`}                   |
| `ok`                | boolean | `true` if `systemctl` returned exit code `0`                                |
| `error`             | string  | `stderr` from `systemctl` if `ok` is `false`, else `null`                   |

```bash
curl http://127.0.0.1:8090/api/status
# → {
#     "llama-server": {
#       "unit": "llama-server.service",
#       "active_state": "active",
#       "sub_state": "running",
#       "enabled_state": "enabled",
#       "main_pid": "4822",
#       "since": "Fri 2026-08-07 14:21:03 CEST",
#       "is_active": true,
#       "is_failed": false,
#       "is_transitioning": false,
#       "ok": true,
#       "error": null
#     }
#   }
```

---

### `GET /api/status/:service_id`

Returns status for a **single** service by its `id`. Unknown `id`s cause a `404`.

* **Auth:** none
* **Response body:** the same object shape as the bulk endpoint.

```bash
curl http://127.0.0.1:8090/api/status/llama-server
# → {"unit": "llama-server.service", "active_state": "active", …}
```

---

### `POST /api/:service_id/:verb`

Issues a systemd action on a service.

* **Auth:** none (handled by reverse proxy — see `docs/security-model.md`).
* **Body:** empty.
* **Method:** `POST` (so the verb must come from the URL, not the method).
* **Verb constraint:** only `start`, `stop`, `restart` are allowed (see `app.py` [line 41]). Anything else returns `400`.
* **Service constraint:** the `id` segment is looked up in `SERVICES_BY_ID` (which is built at startup from `load_services()`); unknown ids return `404`.

| Field      | Type    | Description                                                                 |
| ---------- | ------- | --------------------------------------------------------------------------- |
| `ok`       | boolean | `true` iff `systemctl <verb> <unit>` exited `0`                             |
| `error`    | string  | `stderr` from `systemctl` if `ok` is `false`, else `null`                   |
| `status`   | object  | Full status object for the service, useful because the UI needs the refreshed state after any mutation. Same shape as responses from `GET /api/status` endpoints. |

```bash
# Example: stop llama-server
curl -X POST http://127.0.0.1:8090/api/llama-server/stop
# → {"ok": true, "error": null, "status": {"unit": "llama-server.service", "active_state": "inactive", …}}

# Example: unknown verb
curl -X POST http://127.0.0.1:8090/api/llama-server/reset
# → {"ok": false, "error": "unsupported action"}   (HTTP 400)

# Example: unknown id
curl -X POST http://127.0.0.1:8090/api/not-real/restart
# → {"ok": false, "error": "unknown service id"}   (HTTP 404)
```

---

### Common errors (JSON)

Every JSON endpoint uses application-defined JSON bodies (not HTTP status alone). Most errors are 4xx:

| Scenario                                      | HTTP  | JSON body                                                  |
| ---------------------------------------------- | ----- | ---------------------------------------------------------- |
| Unknown service id in status or action endpoint | 404   | `{"ok": false, "error": "unknown service id"}`            |
| Unsupported verb (`unmount`, `stop --now`, …)  | 400   | `{"ok": false, "error": "unsupported action"}`            |
| `systemctl` failed (service doesn't exist, systemd error) | 200 | `{"ok": false, "error": "<stderr>", "status": <…>}` Note: an `ok: false` response from `POST /:id/:verb` is still `200` because the command itself succeeded at the subprocess boundary; the error is surfaced in the JSON. This is the existing behavior in `app.py` [lines 79–84]. |
| `systemctl show` returned a non-zero exit code | 200   | `{"ok": false, "error": "<stderr>", …}`                    |
| Subprocess `subprocess.run()` itself threw (timeout, missing `sudo`, missing `systemctl`, etc.) | 200 | `{"ok": false, "error": "<str(exception)>"}` (via `run_systemctl` in `app.py` [lines 36–44]) |

---

## Internal implementation notes

* **Sudoers invocation**: action endpoints call `sudo systemctl <verb> <unit>` (run via `/usr/bin/sudo` per `app.py` [lines 29–31]; the path is resolved at import time so any changes to the `sudo` location after app start are not picked up).
* **Timing**: `systemctl show …` calls have a hard timeout of **15 s** in `subprocess.run(timeout=15)` (`app.py` [line 37]). Timeouts are treated as internal errors and surfaced as `ok:false`.
* **No CSRF protection**: the action endpoint must be placed behind an auth-aware reverse proxy to prevent unauthorised use from malicious third-party sites. See `docs/security-model.md`.
* **`SERVICES` list is server-side only**: it is loaded once at startup from `services.load_services()`. Changes to `services.json` or the env vars are **not** picked up without restarting the app.
* **`ALLOWED_VERBS` set** (`{"start", "stop", "restart"}`) is loaded by `app.py` [line 41].
* **`STATUS_FIELDS`** (the fields requested from `systemctl show`) is `ActiveState,SubState,UnitFileState,MainPID,ExecMainStartTimestamp` (`app.py` [line 42]).

---

## Quick reference

```
GET   /                          HTML UI
GET   /api/services              JSON list of configured services
GET   /api/status                JSON bulk status, keyed by id
GET   /api/status/:service_id    JSON single status
POST  /api/:service_id/:verb     start|stop|restart — empty body, URL-encoded verb
```
