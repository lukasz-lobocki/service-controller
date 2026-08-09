#!/usr/bin/env python3
"""
Print a sudoers snippet covering every service in the current config
(services.json / SYSTEMD_SERVICES / SYSTEMD_SERVICE — same resolution
as app.py, via services.py).

Usage:
    python3 scripts/gen_sudoers.py [--user service-controller]

Review the output, then install it:
    python3 scripts/gen_sudoers.py > /tmp/service-controller-sudoers
    sudo visudo -c -f /tmp/service-controller-sudoers   # validate first
    sudo cp /tmp/service-controller-sudoers /etc/sudoers.d/service-controller

Re-run this any time services.json changes and re-install — the
sudoers file has to stay in lockstep with the app's service list, or
start/stop for a newly added service will fail with a permission
error even though the app itself sees it fine.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ServiceConfigError, load_services  # noqa: E402


def alias_name(service_id: str) -> str:
    return "SVC_CTL_" + service_id.upper().replace("-", "_")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="service-controller", help="system user running service-controller")
    args = parser.parse_args()

    try:
        services = load_services()
    except ServiceConfigError as exc:
        sys.exit(f"config error: {exc}")

    print(f"# service-controller sudoers — generated for {len(services)} service(s)")
    print("# Review before installing. Validate with: visudo -c -f <this file>")
    print()

    alias_names = []
    for svc in services:
        name = alias_name(svc["id"])
        alias_names.append(name)
        cmds = ", ".join(f"/usr/bin/systemctl {verb} {svc['unit']}"
                          for verb in ("start", "stop", "restart"))
        print(f"Cmnd_Alias {name} = {cmds}")

    print()
    print(f"{args.user} ALL=(root) NOPASSWD: {', '.join(alias_names)}")


if __name__ == "__main__":
    main()
