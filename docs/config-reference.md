# Configuration Reference

> Covers `services.json` schema, configuration resolution order,
> environment variables, validation rules, and example configurations.

---

## 1. `services.json` — Schema

`services.json` is a **JSON array** at the top level. Each element
describes one managed system service and may carry three fields.
Only `unit` is mandatory; `id` and `label` can be omitted, in which
case the runtime derives sensible defaults.

### 1.1 Fields

| Field     | Required | Type   | Description |
|-----------|----------|--------|-------------|
| `unit`    | **yes**  | string | Full systemd unit name, e.g. `llama-server.service`. Validated against [`UNIT_RE`](#31-unit-regex) at load time. |
| `id`      | no       | string | Internal identifier used in URLs and sudoers rules. If missing, **derived** from `unit` via [`_slugify`](#13-derivation-logic). Validated against [`ID_RE`](#32-id-regex) at load time. |
| `label`   | no       | string | Human-readable name shown on the dashboard. If missing, **derived** from `id` via [`_titleize`](#13-derivation-logic). |

### 1.2 Derivation Logic

Both optional fields are inferred when absent:

```
id       ⇒ slugify(unit):
           1. Strip trailing `.service`
           2. Lowercase everything
           3. Replace every run of non-alphanumeric/dash characters with `-`
           4. Strip leading/trailing `-`
           5. If empty after that, fall back to `"service"`

label    ⇒ titleize(id):
           1. Split `id` on `-`
           2. Capitalize each word
           3. Join with single spaces
```

Examples:

| `unit`                        | automatic `id`        | automatic `label`         |
|-------------------------------|-----------------------|---------------------------|
| `llama-server.service`        | `llama-server`        | `Llama Server`            |
| `flm.service`                 | `flm`                 | `Flm`                     |
| `llama-cpp-strixhalo.service` | `llama-cpp-strixhalo` | `Llama Cpp Strixhalo`     |

### 1.3 Full Example (from `services.example.json`)

```json
[
  {
    "id":      "llama-gpu-strixhalo",
    "unit":    "llama-cpp-strixhalo.service",
    "label":   "StrixHalo llama Ornith (GPU)"
  },
  {
    "id":      "fastflowlm-npu",
    "unit":    "flm.service",
    "label":   "StrixHalo FastFlowLM Gemma (NPU)"
  },
  {
    "id":      "llama-gpu-l",
    "unit":    "llama-cpp-l.service",
    "label":   "llama Laguna (GPU)"
  },
  {
    "id":      "llama-gpu-m",
    "unit":    "llama-cpp-m.service",
    "label":   "llama Mistral (GPU)"
  },
  {
    "id":      "llama-gpu-q",
    "unit":    "llama-cpp-q.service",
    "label":   "llama Qwen (GPU)"
  }
]
```

### 1.4 Minimal Valid Form

A single entry is sufficient — the bare minimum for the app to run is:

```json
[{"unit": "llama-server.service"}]
```

The runtime will auto-infer `id` → `llama-server` and `label` →
`Llama Server`.

---

## 2. Configuration Resolution Order

The runtime loads the configured services in the order below and stops
at the **first source that successfully provides data**.
Earlier sources take precedence — sources at the bottom are evaluated
only when all above are absent or unresolvable.

| # | Source                                | How it's resolved                                       |
|---|---------------------------------------|---------------------------------------------------------|
| 1 | `SERVICES_CONFIG` env var             | Treats the variable as an **absolute file path** to a JSON config. If the path exists and parses as a list, it's used. |
| 2 | `services.json` next to `services.py` | Absolute path derived from `__file__`. Specifically `/opt/service-controller/services.json`. |
| 3 | `SYSTEMD_SERVICES` env var            | Comma-separated list of unit names (`"unit1.service, unit2.service"`). Each is wrapped in `{"unit": …}`. |
| 4 | `SYSTEMD_SERVICE` env var             | Single unit name (`"llama-server.service"`). Wrapped in `[{"unit": …}]` for single-service runs. |
| 5 | Default fallback                      | `[{"unit": "llama-server.service"}]` — the only source guaranteed to be available. |

### 2.1 Pseudocode

```python
env_services_config = os.environ.get("SERVICES_CONFIG")
if env_services_config and os.path.exists(env_services_config):
    return parse_json_list(env_services_config)          # (1)

default_json_path = os.path.join(os.path.dirname(__file__), "services.json")
if os.path.exists(default_json_path):
    return parse_json_list(default_json_path)           # (2)

env_systemd_services = os.environ.get("SYSTEMD_SERVICES")
if env_systemd_services:
    return split_comma(env_systemd_services)            # (3)

env_systemd_service = os.environ.get("SYSTEMD_SERVICE")
if env_systemd_service:
    return single(env_systemd_service)                  # (4)

return [{"unit": "llama-server.service"}]               # (5)
```

No validation has yet been applied at this point — each raw entry is
checked by `UNIT_RE` and `ID_RE` only after the resolution pipeline.

---

## 3. Environment Variables

| Variable | Type                        | Example | Description |
|----------|-----------------------------|---------|-------------|
| `SERVICES_CONFIG` | string (absolute path) | `/data/config/my-services.json` | Path to a JSON file containing a service list. If the file exists, its contents
are used verbatim (preceding any local
`services.json`). The file is loaded as-is; this is the only var that points at an
external file. |
| `SYSTEMD_SERVICES` | string (comma-separated) | `"flm.service, llama-cpp.service"` | Comma-separated list of direct unit names; each `{"unit": …}` entry is auto-expanded
and validated against `UNIT_RE`. |
| `SYSTEMD_SERVICE` | string (single unit) | `"llama-server.service"` | Legacy single-service var. Kept for backward compatibility with the original
one-service deployment. |

### Comma semantics in `SYSTEMD_SERVICES`

The runtime does `os.environ["SYSTEMD_SERVICES"].split(",")`, then strips
whitespace from each token. This means:

- Empty items are silently skipped (e.g. `",foo,,bar," → ["foo", "bar"]`).
- Leading/trailing whitespace around a token is ignored:
  `" a.service , b.service "` → `["a.service", "b.service"]`.
- Quotes are **not** interpreted — `'"foo.service"'` is treated literally.
- The empty string (`""`) counts as "present" only if `os.environ.get()`
  returns truthy; an empty value is falsy and will fall through to the
  next source in the resolution order.

---

## 4. Validation Rules

All entries are validated **after** resolution. Errors surface as a
`ServiceConfigError` (which is a `ValueError` subclass); the
application (`app.py`) catches it at `main()`, prints the message to
stderr, and **exits with code 1**. There is no silent fallback — bad
config is a fatal startup error.

### 4.1 `UNIT_RE` — systemd unit name

```
^[A-Za-z0-9@_.\-]+\.service$
```

| Component                                    | Meaning |
|----------------------------------------------|---------|
| `^ … $`                                      | anchored, whole string |
| `[A-Za-z0-9@_.\-]+`                          | one or more letters, digits, `@`, `_`, `.`, or `-` |
| `\.service$`                                 | literal `.service` suffix |

**Allows**: `flm.service`, `llama-cpp.service`, `foo-bar-1.service`,
`my@unit.service`.
**Rejects**: bare slashes, spaces, globbing, paths like `/etc/systemd/...`,
names missing the `.service` tail.

In short: any name systemd (and sudoers `Cmnd_Alias`)
finds safe.

### 4.2 `ID_RE` — internal identifier

```
^[a-z0-9][a-z0-9-]*$
```

| Component                                     | Meaning |
|-----------------------------------------------|---------|
| `^ … $`                                       | anchored, whole string |
| `[a-z0-9]`                                    | must start with a lowercase letter or digit |
| `[a-z0-9-]*`                                  | any number of lowercase letters, digits, or hyphens follow |

**Allows**: `llama-server`, `fastflowlm-npu`, `gpu0`.
**Rejects**: uppercase (`Llama`), leading `-` (`-foo`), trailing `-`
(`foo-`), dots or underscores (`foo.bar`).

If `id` is *explicitly* provided and fails the regex the same fatal
`ServiceConfigError` is raised.

### 4.3 Duplicate IDs

Independent of regex, every `id` in the loaded list must be unique. Two
entries with the same `id` — explicit or derived — raise
`ServiceConfigError`.

### 4.4 Other checks during load

| Condition | Effect |
|-----------|--------|
| Empty list after resolution | `ServiceConfigError("no services configured")` |
| Entry missing `unit` key | `ServiceConfigError(f"service entry missing 'unit': {entry!r}")` |
| `JSON` file is not parsed or is not a list at the top level | `ServiceConfigError(f"{config_path} must contain a JSON list")` |

---

## 5. Example Configurations

### 5.1 Minimal — one service, no overrides

```json
[{"unit": "llama-server.service"}]
```

### 5.2 Production-style — multiple entries with explicit ids & labels

(from `services.example.json`):

```json
[
  {"id": "llama-gpu-strixhalo",
   "unit": "llama-cpp-strixhalo.service",
   "label": "StrixHalo llama Ornith (GPU)"},
  {"id": "fastflowlm-npu",
   "unit": "flm.service",
   "label": "StrixHalo FastFlowLM Gemma (NPU)"}
]
```

### 5.3 Simple — env-var override (comma-separated)

```bash
export SYSTEMD_SERVICES="flm.service, llama-cpp.service"
```
→ produces two entries, both using the derived `id`/`label`.

### 5.4 Single service — backward-compatible env var

```bash
export SYSTEMD_SERVICE="llama-server.service"
```
→ produces `[{"unit": "llama-server.service"}]`.

### 5.5 External config file — `SERVICES_CONFIG`

```bash
SERVICES_CONFIG=/etc/my-infra/services.json
```
→ reads `/etc/my-infra/services.json`. The file itself can be in any
of the formats above (min `{"unit": …}`, full `services.example.json`,
even a *different* path to a symlinked `services.json` — the runtime
only cares that the path exists _before_ it falls through to the built
in one).

---

## 6. Quick Summary

| Concern                    | Where to configure it                  |
|----------------------------|----------------------------------------|
| Add / remove services     | Edit `services.json` or set
`SERVICES_CONFIG` to point at your own file |
| Single service override   | `SYSTEMD_SERVICE=foo.service`          |
| Comma-separated list      | `SYSTEMD_SERVICES=a.service,b.service` |
| External config file      | `SERVICES_CONFIG=/abs/path.json`       |
| Fail-fast on typo         | `UNIT_RE` / `ID_RE` / duplicate `id`   |
| Safe value for everything | `[{"unit": "llama-server.service"}]`   |