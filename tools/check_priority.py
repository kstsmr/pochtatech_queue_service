"""Validate the JSON-compatible YAML priority configuration without dependencies."""

import json
from pathlib import Path


def validate(config):
    def keys(value, expected, label):
        if not isinstance(value, dict) or set(value) != set(expected):
            raise ValueError(f"{label}: unexpected or missing keys")

    def integer(value, minimum, maximum, label):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{label}: expected integer in [{minimum}, {maximum}]")

    keys(config, ("schema_version", "rule_version", "early_minutes", "grace_minutes",
                  "max_wait_minutes", "levels"), "config")
    integer(config["schema_version"], 2, 2, "schema_version")
    integer(config["rule_version"], 1, 1_000_000, "rule_version")
    for name in ("early_minutes", "grace_minutes"):
        integer(config[name], 0, 120, name)
    keys(config["max_wait_minutes"], ("prebooking", "qr", "walk_in"), "max_wait_minutes")
    for name, value in config["max_wait_minutes"].items():
        integer(value, 1, 240, name)
    levels = config["levels"]
    keys(levels, ("overdue", "appointment", "qr", "walk_in", "late_prebooking"), "levels")
    for name, value in levels.items():
        integer(value, 0, 100, name)
    if any(levels["overdue"] >= levels[name] for name in levels if name != "overdue"):
        raise ValueError("overdue must outrank every other level")
    if any(levels["appointment"] > levels[name] for name in ("qr", "walk_in", "late_prebooking")):
        raise ValueError("appointment must not rank below ordinary tickets")
    if config["max_wait_minutes"]["prebooking"] < config["early_minutes"] + config["grace_minutes"]:
        raise ValueError("prebooking max wait must cover the full appointment window")


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "config" / "priority.yaml"
    validate(json.loads(path.read_text(encoding="utf-8")))
    print("Priority configuration is valid (schema v2).")
