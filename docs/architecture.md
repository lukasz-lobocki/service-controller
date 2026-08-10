# Architecture Deep-Dive

## 1. Component Map

| File | Role | Key Lines |
|---|---|---|
| `app.py` | Flask web app — serves the UI and exposes 7 REST endpoints that drive `systemctl` | `app.py:1-185` |
| `services.py` | Configuration loader: JSON → env vars → fallback default. Validates unit names and generates `id`/`label` | `services.py:1-116` |
| `service-controller.service` | systemd `Type=simple` unit that runs `app.py` as user `service-controller`, binds to loopback:8090 | `service-controller.service:1-23` |
| `scripts/gen_sudoers.py` | Generates `/etc/sudoers.d/service-controller` allowing the `service-controller` user to run `systemctl start/stop/restart` for each configured unit without a password | `scripts/gen_sudoers.py:1-72` |
| `templates/index.html` | Jinja template — renders the empty `<rack>` and embeds `window.__SERVICES__` from `services.json` | `templates/index.html:1-53` |
| `static/app.js` | Client-side polling loop (5 s), `act(verb)` dispatcher, renders each panel via template cloning | `static/app.js:1-182` |
| `services.example.json` | Sample config shipped with the project — five LLM units for a workstation GPU | `services.example.json:1-7` |

### File-level responsibilities

```
service-controller.service
  → ExecStart → app.py
                     ├── render_template("index.html", services=SERVICES)  ──► static/app.js + index.html
                     ├── /api/services    ──► jsonify(SERVICES)
                     ├── /api/status      ──► {<id>: get_status(<unit>)}     ← polls /api/status all 5 units
                     ├── /api/status/<id> ──► get_status(unit)
                     └── /api/<id>/start|stop|restart  ──► run_systemctl([verb, unit], use_sudo=True)
```

## 2. Startup Sequence

```
systemd reads service-controller.service (line 1)
  │  User=service-controller, ExecStart=<venv>/bin/python /opt/service-controller/app.py
  ▼
/app.py begins execution                           (app.py:1)
  │  "import os"                                   (app.py:8)
  │  from services import load_services            (app.py:10)
  │  from flask import Flask, jsonify, render_template
  │  app = Flask(__name__)                        (app.py:12)
  ▼
_services.py resolution                            (app.py:15)
  │  config_path ← env SERVICES_CONFIG OR services.json next to app.py
  │  if file exists → json.load(list)
  │  elif SYSTEMD_SERVICES set → [{"unit": <csv>}]
  │  elif SYSTEMD_SERVICE set → [{"unit": <single>}]
  │  else → [{"unit": "llama-server.service"}]
  ▼
load_services() runs                               (app.py:18)
  │  validates each unit via _validate_unit(unit)  (services.py:85)
  │  generates id ← entry.get("id") or _slugify(unit)
  │  validates id via ID_RE regex                  (services.py:34)
  │  builds dict {id: {id, unit, label}}
  ▼
SERVICES (list) + SERVICES_BY_ID (dict) + run_systemctl
  │  are now bound at module scope                   (app.py:21-28)
  ▼
__main__ block                                     (app.py:181)
  │  PORT = os.environ.get("PORT", 8090)
  │  HOST = os.environ.get("HOST", "127.0.0.1")
  │  app.run(host=HOST, port=PORT)                  (app.py:185)
```

## 3. Request/Response Flow

### 3.1 GET `/` — index

`app.py:30-31`

```
render_template("index.html", services=SERVICES)
  │  → index.html receives Jinja variable {{ services }}
  │  → JSON-serializes to window.__SERVICES__ (line 48)
  │  → response: 200, text/html
```

### 3.2 GET `/api/services` — static service list

`app.py:34-35`

```
jsonify([{"id", "unit", "label"}, ...])    → 200
  │  returns the immutable SERVICES list as JSON
```

### 3.3 GET `/api/status` — bulk status (one round trip for all services)

`app.py:38-45`

```
{svc["id"]: get_status(svc["unit"]) for s in SERVICES}   → 200
  │  calls get_status() for every configured unit
  │  returns dict keyed by id, useful for /api/status polls
```

### 3.4 GET `/api/status/<service_id>` — single service status

`app.py:47-52`

```
lookup = SERVICES_BY_ID.get(service_id)
if not lookup: → 404 {"ok": False, "error": "unknown service id"}
return jsonify(get_status(svc["unit"]))              → 200
```

### 3.5 POST `/api/<service_id>/<verb>` — start/stop/restart

`app.py:54-68`

```
svc     = SERVICES_BY_ID.get(service_id)
if not svc:                       → 404 {"ok": False, "error": "unknown service id"}
if verb not in ALLOWED_VERBS:     → 400 {"ok": False, "error": "unsupported action"}
code, _, err = run_systemctl([verb, svc["unit"]], use_sudo=True)
return {
  "ok": code == 0,
  "error": err if code != 0 else None,
  "status": get_status(svc["unit"]),
}
```

`run_systemctl()` uses `subprocess.run` with `check=False`, `capture_output=True`, and passes `sudo -u service-controller` when `use_sudo=True` (i.e. for action verbs).

### 3.6 GET `/api/stop` — deprecated single-service alias (optional)

### 3.7 POST `/api/stop` — deprecated action alias (optional)

## 4. systemctl Commands

### Status (no sudo)

`STATUS_FIELDS = "ActiveState,SubState,UnitFileState,MainPID,ExecMainStartTimestamp"`

```bash
systemctl status --no-pager --plain \
  -n 0 --output-fields="ActiveState,SubState,UnitFileState,MainPID,ExecMainStartTimestamp" \
  <unit>
```

Executed inside `get_status()` as `subprocess.run(["systemctl", "status", ...], ...)` for every GET `/api/status*` request.

### Actions (sudo required)

The app runs with `User=service-controller`, which is not permitted to call `systemctl start/stop/restart` directly, so `run_systemctl(..., use_sudo=True)` wraps the command with `sudo -u service-controller`:

```bash
sudo -u service-controller /usr/bin/systemctl start  <unit>
sudo -u service-controller /usr/bin/systemctl stop   <unit>
sudo -u service-controller /usr/bin/systemctl restart <unit>
```

Enabled by the generated sudoers file in `/etc/sudoers.d/service-controller`.

### Allowed verbs

```python
ALLOWED_VERBS = {"start", "stop", "restart"}   # app.py: line 60
```

## 5. Config Loading

Located in `services.py`, the loading chain is a priority cascade (first match wins):

| Priority | Source | Env/var fallback |
|---|---|---|
| 1 | JSON file | `os.environ["SERVICES_CONFIG"]` or `services.json` next to `app.py` |
| 2 | Comma-separated units | `SYSTEMD_SERVICES` env var |
| 3 | Single unit | `SYSTEMD_SERVICE` env var (legacy) |
| 4 | Hardcoded default | `{"unit": "llama-server.service"}` |

### Validation regexes

```python
UNIT_RE = re.compile(r'^[A-Za-z0-9@_.\-]+\.service$')          # services.py:33
ID_RE   = re.compile(r'^[a-z0-9][a-z0-9-]*$')                   # services.py:34
```

The unit regex strips the `.service` suffix for slug generation, then re-attaches.

### ServiceError handling

Invalid inputs raise `ServiceConfigError` (inherits `ValueError`), which is caught in `gen_sudoers.py:38` and in the app startup via a hard-fail `except SystemExit`:

```python
except ServiceConfigError as exc:
    sys.exit(f"config error: {exc}")
```

## 6. Sudo Rules

`scripts/gen_sudoers.py` reuses `services.load_services()` so the sudoers file exactly matches the app's current config:

```python
# gen_sudoers.py:23-31
def alias_name(service_id: str) -> str:
    return "SVC_CTL_" + service_id.upper().replace("-", "_")
```

For each service an alias `Cmnd_Alias` is emitted, limiting the allowed verbs to `start`, `stop`, `restart`:

```bash
Cmnd_Alias SVC_CTL_LLAMA_STRI_HALO = /usr/bin/systemctl start llama.service, \
                                      /usr/bin/systemctl stop llama.service, \
                                      /usr/bin/systemctl restart llama.service
```

Final rule:

```bash
service-controller ALL=(root) NOPASSWD: SVC_CTL_LLAMA_STRI_HALO, ..., SVC_CTL_OTHER
```

The `--user` flag (default `service-controller`) controls the user on the final Allow line. **The sudoers file must be re-generated and re-installed whenever `services.json` changes** — the app itself doesn't check rules at runtime.

## 7. Frontend Loading

### 7.1 Embedding services on the server

`templates/index.html:48`

```html
<script>
  window.__SERVICES__ = {{ services|tojson }};
</script>
```

The server serializes `SERVICES` (the `list[dict]` produced by `services.py`) into JavaScript. This happens once per page load — no extra API round-trip before the first paint.

### 7.2 Panel template cloning

`static/app.js:52-53` — `buildPanels()`:

```js
const tmpl = document.getElementById('panel-template');
for (const svc of SERVICES) {
    const node = tmpl.content.firstElementChild.cloneNode(true);
    node.dataset.id = svc.id;
    node.querySelectorAll('[data-el]').forEach(el => { els[el.dataset.el] = el; });
    els.label.textContent = svc.label;
    els['unit-name'].textContent = svc.unit;
    panels[svc.id] = { els, busy: false };
    rack.appendChild(node);
}
```

Each panel gets `data-el` attributes bound to reference objects: `led`, `state-word`, `sub-state`, `enabled-state`, `since`, `toggle-btn`, `restart-btn`, `error-banner`, `unit-name`, `label`.

### 7.3 Polling loop

```js
const POLL_MS = 5000;   // app.js:1
async function pollAll() {
    const res = await fetch('/api/status');   // app.js:148
    const data = await res.json();
    for (const id of Object.keys(data)) render(id, data[id]);
}
buildPanels();
pollAll();                        // first fire   (app.js:181)
setInterval(pollAll, POLL_MS);   // recurring     (app.js:182)
```

### 7.4 Status field mapping

`get_status()` parses the `--output-fields`-style `systemctl status` output and returns:

| JSON key | Source column | Mapping |
|---|---|---|
| `active_state` | `ActiveState` | raw string |
| `sub_state` | `SubState` | raw string |
| `enabled_state` | `UnitFileState` | raw string |
| `main_pid` | `MainPID` | string, empty if no pid |
| `since` | `ExecMainStartTimestamp` | raw timestamp string |
| `is_active` | — | `active_state == "active"` |
| `is_failed` | — | `active_state == "failed"` |
| `is_transitioning` | — | `active_state in ("activating","deactivating")` |
| `ok` | — | `code == 0` (subprocess exit code) |
| `error` | — | stderr if exit code ≠ 0, else null |

## 8. Data Structures

### 8.1 `SERVICES` (module-level list)

```python
[
  {"id": "llama-gpu-strixhalo", "unit": "llama-cpp.service", "label": "StrixHalo llama Ornith (GPU)"},
  {"id": "fastflowlm-npu",      "unit": "flm.service",       "label": "StrixHalo FastFlowLM Gemma (NPU)"},
  ...
]
```

Built in `services.py:load_services()` lines 88–116. Returned by `GET /api/services` and embedded in `templates/index.html` line 48.

### 8.2 `SERVICES_BY_ID` (module-level dict)

```python
{
  "llama-gpu-strixhalo": {"id": "llama-gpu-strixhalo", "unit": "llama-cpp.service", "label": "StrixHalo llama Ornith (GPU)"},
  ...
}
```

Same loop in `services.py:88-116`, keyed by `id`. Used in `GET /api/status/<id>` and `POST /api/<id>/<verb>` for fast lookup.

### 8.3 `get_status(unit)` return dict

`app.py: lines 82-89` build the response:

```python
{
    "unit": "<unit>",
    "active_state": "active|inactive|failed|activating|…",   # from ActiveState column
    "sub_state": "running|exited|…",                          # SubState column
    "enabled_state": "enabled|disabled|…",                    # UnitFileState column
    "main_pid": "<pid>|",                                      # MainPID column
    "since": "<timestamp>|",                                   # ExecMainStartTimestamp column
    "is_active": bool,                                         # computed: ActiveState == "active"
    "is_failed": bool,                                         # computed: ActiveState == "failed"
    "is_transitioning": bool,                                  # computed: ActiveState in (activating, deactivating)
    "ok": bool,                                                # True iff exit code == 0
    "error": str | None,                                       # stderr or None
}
```

Status calls happen inside `app.py:128-141` (bulk) and `app.py:149-166` (single), and again at the end of each action request in `app.py:168-180`.

### 8.4 `_raw_entries()` output shape

`services.py: lines 60-83` — raw entries before validation:

```python
[{"unit": "llama-cpp.service", "id": "...", "label": "..."}]    # JSON file
[{"unit": u.strip()}, ...]                                      # SYSTEMD_SERVICES comma CSV
[{"unit": "single.service"}]                                    # SYSTEMD_SERVICE
[{"unit": "llama-server.service"}]                              # default
```

## Appendix: Full `systemctl status` invocation

`get_status()` runs the following exact subprocess command:

```bash
systemctl --user status --no-pager --plain -n 0
  --output-fields=ActiveState,SubState,UnitFileState,MainPID,ExecMainStartTimestamp
  <unit>
```

The output is parsed by splitting on `\n`, then on `:` to build the dict above. Each field gets its column header as key and everything after `:` as value. Empty values stay empty strings. Timestamps are returned verbatim (not parsed to JavaScript `Date` objects — that's the client's job).