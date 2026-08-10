# Security Model

> Source: `app.py`, `scripts/gen_sudoers.py`, `services.py`, `tests/security_test*.py`, `tests/test_sudoers*.py`, `service-controller.service`.

This document describes how `service-controller` is designed to be safe to expose on a private network with a reverse-proxy auth layer. It covers:

1. **Sudoers isolation** — only `start`, `stop`, `restart` on allow-listed services
2. **Allowlist validation** — config-driven, regex-validated at load time
3. **No built-in authentication** — reverse-proxy responsibility
4. **Threat model** — what the design defends against and does not

---

## 1. Sudoers isolation

`service-controller` is designed to run as an **unprivileged user** (the system user chosen when generating the sudoers rule — typically `service-controller`). The app itself has **no root privileges**: every systemd mutation goes through `sudo systemctl <verb> <unit>`, where `sudo` enforces the tight permission boundary.

The sudoers rule is generated from the same `services.json` (or env var) that seeds the app, so it **stays in lockstep with what the app can reach**. Re-run `scripts/gen_sudoers.py` any time `services.json` changes and `sudo cp /tmp/service-controller-sudoers /etc/sudoers.d/service-controller` to refresh. See `scripts/gen_sudoers.py` [docstring].

### How the sudoers rule is built

For each configured service, `gen_sudoers.py` emits one `Cmnd_Alias` covering exactly three verbs:

```
Cmnd_Alias SVC_CTL_llama_server = /usr/bin/systemctl start llama-server.service, /usr/bin/systemctl stop llama-server.service, /usr/bin/systemctl restart llama-server.service
```

These aliases are then joined into a single rule granting the target user (defaults to `service-controller`, overridable with `--user`, see `scripts/gen_sudoers.py` [lines 31, 47]):

```
service-controller ALL=(root) NOPASSWD: SVC_CTL_llama_server, SVC_CTL_other_service
```

### What the sudoers rule permits

| Allowed by `Cmnd_Alias` | NOT allowed by the rule |
| ------------------------ | ------------------------ |
| `/usr/bin/systemctl start <configured unit>.service` | `/usr/bin/systemctl stop <configured unit>.service` *only* — restart is also permitted; no others |
| `/usr/bin/systemctl stop <configured unit>.service` | `/usr/bin/systemctl <any other verb> <configured unit>` (restart, enable, disable, status, …) |
| `/usr/bin/systemctl restart <configured unit>.service` | `/usr/bin/systemctl <configured unit> <any other action>` (anything not in the exact alias list) |
| (nothing else) | Any `/foo/bar` other than the three exact `/usr/bin/systemctl <verb> <unit>` combos for the configured units |

`services.py` [line 17–18] enforces a conservative systemd unit-name regex (`^[A-Za-z0-9@_.\-]+\.service$`) to keep these unit names safe to drop into a `Cmnd_Alias`.

### Hardening flags in the systemd unit

`service-controller.service` enables `PrivateTmp=true` (`[Service]` section, line 21). `NoNewPrivileges=false` is left as the default for that flag to allow `sudo` to actually do its job even when the unit is otherwise constrained. The unit also sets `User=service-controller`, `Group=service-controller`, `ProtectSystem=strict`, and `ReadWritePaths=/opt/service-controller` to limit filesystem exposure, though `ProtectSystem=strict` may need to be relaxed to `read-only` if `sudoers` is tightened further.

---

## 2. Allowlisting (config-driven, validated)

### Resolution order

`services.load_services()` in `services.py` [lines 41-60] reads the allow-list from:

1. A JSON config file (env var `SERVICES_CONFIG`, defaulting to `<services.py>/services.json`) — `services.py` [line 35–36]
2. `SYSTEMD_SERVICES` — comma-separated unit names (`services.py` [line 37–39])
3. `SYSTEMD_SERVICE` — single legacy unit name (`services.py` [line 40-41])
4. Fallback to `llama-server.service` (`services.py` [line 42-43])

### Validation (happens once at startup)

Both unit names and `id`s are validated by regex before they reach the app:

* **Unit name:** `^[A-Za-z0-9@_.\-]+\.service$` (`services.py` [line 17–18]) — rejects any unit name that isn't a well-formed systemd unit and ends in `.service`.
* **Id:** `^[a-z0-9][a-z0-9-]*$` (`services.py` [line 19]) — lowercase alphanumeric + hyphens, starting with alphanumeric.
* **Duplicates:** Identities are deduplicated (`services.py` [lines 56–57]); duplicate ids raise `ServiceConfigError`.
* **Missing `unit` field:** entries without `unit` key are rejected when reading JSON config (`services.py` [lines 47–49]), and entries must be lists (`services.py` [lines 45–46]).

If any validation fails, `load_services()` raises `ServiceConfigError`, which causes `app.py` to call `sys.exit(f"service-controller config error: {exc}")` immediately on startup (`app.py` [lines 23–26]).

### Consequences

* **Ids are never user-supplied:** the `id` field in the allow-list comes from config (auto-generated as a slug from the unit unless explicitly given). Attackers have no channel to introduce arbitrary ids.
* **If `services.json` has an invalid unit, the process refuses to start** — a failure-to-verify-at-load-time failure is worse than a silent start and may indicate a typo in config, which the regex catches.

---

## 3. No built-in authentication

`service-controller` doesn't:

* Read `Authorization` / `X-Auth-Token` / any other headers
* Check session cookie state
* Enforce HTTP method restrictions on static endpoints

The app is designed for placement **behind a reverse proxy** (e.g. Caddy with an OIDC `forward_auth` provider, nginx with HTTP basic auth or OIDC, HashiCorp Vault's transparent encryption, HTPC, or any tool that authenticates before forwarding the request). This is explicitly documented:

> The app itself has no authentication. Put it behind a reverse proxy that handles auth.
> — `app.py` [docstring line – Security model: "no authentication"]

### Why reverse-proxy auth is a feature

Keeping auth at the HTTP edge means:

* The Python app stays small and auditable.
* It shares the same auth infrastructure (OIDC, SAML, mTLS, …) as the rest of your services.
* It avoids the anti-pattern of "every internal tool implements its own password system".

---

## 4. Threat model

Defences vs threats (this tool does **not** pretend to defend against everything):

### Mitigated threats

| Threat                                                  | Defence                                                                         |
| ------------------------------------------------------- | ------------------------------------------------------------------------------- |
| *Unprivileged app, no root outside sudoers*             | The `service-controller` user has no sudoers rule granting `sudo` access to the shell or to arbitrary commands — only the three specific `/usr/bin/systemctl <verb> <unit>` commands for each configured unit. See `scripts/gen_sudoers.py` [lines 35–47]. |
| *An attacker-supplied unit name via HTTP request*       | `SERVICES_BY_ID` is server-side. The id segment on the URL is looked up against the allow-list; unknown ids return `404` (`app.py` [lines 71–74]). The unit name is never formed from request input. |
| *An attacker-supplied verb via HTTP request*            | Only the subset `{"start", "stop", "restart"}` (`app.py` [line 41]) is accepted. Anything else returns `400` (`app.py` [lines 76–78]). |
| *An attacker supplying a sub-command (`--force`, …)*    | `run_systemctl` in `app.py` [lines 32–38] concatenates `[verb, unit]` from two sources (URL and hardcoded), but the sudoers rule requires the **exact** command string `/usr/bin/systemctl <verb> <unit>`; any non-exact argv (e.g. one with `--force`) will be rejected by `sudo` before `systemctl` ever sees it. |
| *A typo'd unit name in `services.json` that reaches sudo* | `services.load_services()` rejects any unit that does not match `^[A-Za-z0-9@_.\-]+\.service$` (`services.py` [line 17–18]); the regexed unit name is then safe to insert directly into the sudoers rule text (`scripts/gen_sudoers.py` [line 40]). |
| *A stale sudoers file after reconfiguring the allow-list* | `gen_sudoers.py` [docstring] tells operators to regenerate and reload the sudoers file after any config change; nothing else in the tooling auto-pushes (this is an intentional trust-boundary between config and OS-level permissions). |
| *Subprocess injection (shell metacharacters, path escapes, …)* | `systemctl` calls are executed as a vector of argv strings: `([SUDO,SYSTEMCTL] + args)`, no shell. The unit name comes from validated config, not from user input at API time. |
| *Process-timeout DoS*                                   | Every `systemctl show` and `systemctl <verb>` call is bounded by `subprocess.run(...,timeout=15)` in `run_systemctl` (`app.py` [lines 36–44]). The browser client also only polls every 5 seconds by default (`static/app.js` [line 1]). |

### Not mitigated (by design)

| Threat                                                    | Why it's outside scope                                                                 |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Unauthorised use of the UI without reverse-proxy auth     | This is the reverse-proxy's responsibility, documented in `app.py` [docstring].          |
| Man-in-the-middle between reverse proxy and browser       | TLS (HTTPS) is the reverse proxy's job. The tool runs on `http://` by default (`HOST=127.0.0.1`; `app.py` [line 99]). |
| Denial-of-service against systemd                       | systemd is one hop behind — tooling does not attempt to defend against all systemd-level DOS. |
| Privilege escalation outside sudoers (kernel, sudo version, …) | The sudoers rule covers exactly those three verbs. Any sudo bug in a system-level package is outside the project scope. |

### What an attacker *with auth* can do

Once authenticated via the reverse proxy, the attacker can:

1. Enumerate every configured service (`GET /api/services`).
2. Read every configured service's live status (`GET /api/status` and `GET /api/status/:id`).
3. Issue `start`, `stop`, or `restart` on every configured service (`POST /api/:id/:verb`).

That is exactly the intended scope of the application. If you need more granular per-service permissions, you would need to deploy the reverse proxy's auth layer at a path/segment level (e.g. `/api/<allowed-service-id>/*`) — which is out of scope for `service-controller`.

---

## 5. Audit trail

`service-controller` does not keep a journal of who started what. For audit logging:

* Capture reverse-proxy access logs (Caddy nginx, …).
* Optionally wrap `sudo` with `auditd`/`sudo -l` audit, which records every elevated `systemctl` invocation regardless of who initiated it.
* systemd journal (`journalctl -u <unit>`) records when a unit's state changed, which correlates with who issued the action.

---

## 6. Configuration summary

| Setting                           | Where it lives                                             |
| --------------------------------- | ---------------------------------------------------------- |
| `services.json` / `SERVICES_CONFIG` / `SYSTEMD_SERVICES` / `SYSTEMD_SERVICE` | `services.py`, lines [6–32](file:///home/la_lukasz/Code/service-controller/services.py#L6-L32) |
| `PORT`, `HOST`                    | env vars, `app.py` [lines 98–100]                          |
| Sudoers rule user                 | `--user` arg in `scripts/gen_sudoers.py` [line 31]; default `service-controller`. Install under `/etc/sudoers.d/` or `/etc/sudoers` |
| systemd unit flags (e.g. `PrivateTmp`, `ProtectSystem`) | `service-controller.service`, `[Service]` block, lines ~16–24 |

---

## Quick hardening checklist

1. [ ] Generate sudoers with `python3 scripts/gen_sudoers.py | sudo tee /etc/sudoers.d/service-controller && sudo visudo -c -f /etc/sudoers.d/service-controller`
2. [ ] Ensure the sudoers file is `0440` (or stricter), owned by `root:root`
3. [ ] Run `service-controller` under the chosen non-root user (the `User=` field in `service-controller.service`)
4. [ ] Confirm the reverse proxy performs authentication before forwarding
5. [ ] Confirm the reverse proxy enforces TLS
6. [ ] (Recommended) Enable `auditd` rules for `auditctl -a always,exit -F arch=b64 -S execve -F euid=0` to capture sudo usage
7. [ ] Re-run `gen_sudoers.py` and reinstall the sudoers file anytime `services.json` changes
