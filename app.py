#!/usr/bin/env python3
"""
service-controller — a minimal web UI to view status and start/stop/restart
a fixed, allow-listed set of systemd services in parallel.

Security model (read this before deploying):
  - The controllable services come entirely from server-side config
    (services.json, or the SYSTEMD_SERVICES / SYSTEMD_SERVICE env
    vars — see services.py). They are never taken from request input.
    A request can only reference a service by the short `id` it was
    assigned in that config; unknown ids are rejected with 404.
  - The app itself should run as an unprivileged user. It shells out
    to `sudo systemctl <verb> <unit>` for start/stop/restart. A
    narrowly scoped sudoers rule should allow exactly those commands
    for exactly the configured units — run `scripts/gen_sudoers.py`
    to generate one from your current config instead of hand-writing
    it. See README.md.
  - This app has NO built-in authentication or CSRF protection. Put
    it behind a reverse proxy that handles auth (e.g. Caddy + an OIDC
    forward_auth provider), or restrict it to a private network/VPN.
    Never expose it directly to the internet.
"""
import os
import subprocess
import sys

from flask import Flask, jsonify, render_template

from services import ServiceConfigError, load_services

app = Flask(__name__)

try:
    SERVICES = load_services()
except ServiceConfigError as exc:
    sys.exit(f"service-controller config error: {exc}")

SERVICES_BY_ID = {s["id"]: s for s in SERVICES}

SYSTEMCTL = "/usr/bin/systemctl"
SUDO = "/usr/bin/sudo"
ALLOWED_VERBS = {"start", "stop", "restart"}
STATUS_FIELDS = "ActiveState,SubState,UnitFileState,MainPID,ExecMainStartTimestamp"


def run_systemctl(args, use_sudo=False):
    cmd = ([SUDO] if use_sudo else []) + [SYSTEMCTL] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return 1, "", str(exc)


def get_status(unit):
    code, out, err = run_systemctl(["show", unit, "-p", STATUS_FIELDS])
    fields = {}
    if code == 0:
        for line in out.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                fields[key] = value

    active_state = fields.get("ActiveState", "unknown")
    return {
        "unit": unit,
        "active_state": active_state,
        "sub_state": fields.get("SubState", "unknown"),
        "enabled_state": fields.get("UnitFileState", "unknown"),
        "main_pid": fields.get("MainPID", "0"),
        "since": fields.get("ExecMainStartTimestamp", ""),
        "is_active": active_state == "active",
        "is_failed": active_state == "failed",
        "is_transitioning": active_state in ("activating", "deactivating"),
        "ok": code == 0,
        "error": err if code != 0 else None,
    }


@app.route("/")
def index():
    return render_template("index.html", services=SERVICES)


@app.route("/api/services")
def api_services():
    return jsonify([{"id": s["id"], "unit": s["unit"], "label": s["label"]} for s in SERVICES])


@app.route("/api/status")
def api_status_all():
    """Bulk status for every configured service, keyed by id — one
    round trip per poll interval regardless of how many services."""
    return jsonify({s["id"]: get_status(s["unit"]) for s in SERVICES})


@app.route("/api/status/<service_id>")
def api_status_one(service_id):
    svc = SERVICES_BY_ID.get(service_id)
    if not svc:
        return jsonify({"ok": False, "error": "unknown service id"}), 404
    return jsonify(get_status(svc["unit"]))


@app.route("/api/<service_id>/<verb>", methods=["POST"])
def api_action(service_id, verb):
    svc = SERVICES_BY_ID.get(service_id)
    if not svc:
        return jsonify({"ok": False, "error": "unknown service id"}), 404
    if verb not in ALLOWED_VERBS:
        return jsonify({"ok": False, "error": "unsupported action"}), 400

    code, _, err = run_systemctl([verb, svc["unit"]], use_sudo=True)
    return jsonify({
        "ok": code == 0,
        "error": err if code != 0 else None,
        "status": get_status(svc["unit"]),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8090))
    # Bind to loopback only by default — put a reverse proxy in front for
    # LAN/internet access rather than binding this directly to 0.0.0.0.
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port)
