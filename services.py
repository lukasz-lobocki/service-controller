"""
Config loading for service-controller's service list.

Resolution order (first match wins):
  1. A JSON config file — path from SERVICES_CONFIG env var, or
     services.json next to this file if that env var isn't set.
  2. SYSTEMD_SERVICES env var — comma-separated unit names.
  3. SYSTEMD_SERVICE env var (legacy, single-service) — kept for
     backward compatibility with the original one-service version.
  4. Fallback default: llama-server.service.

Every unit name is validated regardless of source, since it ends up
inside a sudoers rule and a systemctl argv — config-file typos should
fail loudly at startup rather than silently produce a broken sudoers
rule.
"""
import json
import os
import re

CONFIG_ENV = "SERVICES_CONFIG"
DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "services.json")

# Conservative systemd unit name pattern: letters/digits plus the
# punctuation systemd itself allows, ending in .service. Not exhaustive
# of everything systemd permits, but anything this strict is safe to
# drop straight into a sudoers Cmnd_Alias and a subprocess argv.
UNIT_RE = re.compile(r'^[A-Za-z0-9@_.\-]+\.service$')
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')


class ServiceConfigError(ValueError):
    pass


def _slugify(unit: str) -> str:
    base = unit[:-len(".service")] if unit.endswith(".service") else unit
    slug = re.sub(r'[^a-z0-9-]+', '-', base.lower()).strip('-')
    return slug or "service"


def _titleize(slug: str) -> str:
    return " ".join(word.capitalize() for word in slug.split("-"))


def _validate_unit(unit: str):
    if not UNIT_RE.match(unit):
        raise ServiceConfigError(
            f"invalid systemd unit name: {unit!r} (expected something like 'name.service')"
        )


def _raw_entries():
    config_path = os.environ.get(CONFIG_ENV, DEFAULT_CONFIG_PATH)
    if os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ServiceConfigError(f"{config_path} must contain a JSON list")
        return data

    if os.environ.get("SYSTEMD_SERVICES"):
        units = [u.strip() for u in os.environ["SYSTEMD_SERVICES"].split(",") if u.strip()]
        return [{"unit": u} for u in units]

    if os.environ.get("SYSTEMD_SERVICE"):
        return [{"unit": os.environ["SYSTEMD_SERVICE"]}]

    return [{"unit": "llama-server.service"}]


def load_services():
    """Return a validated list of {id, unit, label} dicts, in config order."""
    entries = _raw_entries()
    if not entries:
        raise ServiceConfigError("no services configured")

    services = []
    seen_ids = set()
    for entry in entries:
        if "unit" not in entry:
            raise ServiceConfigError(f"service entry missing 'unit': {entry!r}")
        unit = entry["unit"]
        _validate_unit(unit)

        service_id = entry.get("id") or _slugify(unit)
        if not ID_RE.match(service_id):
            raise ServiceConfigError(
                f"invalid service id: {service_id!r} (use lowercase letters, digits, hyphens)"
            )
        if service_id in seen_ids:
            raise ServiceConfigError(f"duplicate service id: {service_id!r}")
        seen_ids.add(service_id)

        label = entry.get("label") or _titleize(service_id)
        services.append({"id": service_id, "unit": unit, "label": label})

    return services
