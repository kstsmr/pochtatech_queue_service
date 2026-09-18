import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


CONFIG_KEYS = {
    "schema_version", "rule_version", "early_minutes", "grace_minutes",
    "max_wait_minutes", "levels",
}
WAIT_KEYS = {"prebooking", "qr", "walk_in"}
LEVEL_KEYS = {"overdue", "appointment", "qr", "walk_in", "late_prebooking"}


def _integer(value: Any, minimum: int, maximum: int, label: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label}: expected integer in [{minimum}, {maximum}]")


def validate_priority_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict) or set(config) != CONFIG_KEYS:
        raise ValueError("priority config has unexpected or missing keys")
    _integer(config["schema_version"], 2, 2, "schema_version")
    _integer(config["rule_version"], 1, 1_000_000, "rule_version")
    for name in ("early_minutes", "grace_minutes"):
        _integer(config[name], 0, 120, name)
    waits = config["max_wait_minutes"]
    if not isinstance(waits, dict) or set(waits) != WAIT_KEYS:
        raise ValueError("max_wait_minutes has unexpected or missing keys")
    for name, value in waits.items():
        _integer(value, 1, 240, f"max_wait_minutes.{name}")
    levels = config["levels"]
    if not isinstance(levels, dict) or set(levels) != LEVEL_KEYS:
        raise ValueError("levels has unexpected or missing keys")
    for name, value in levels.items():
        _integer(value, 0, 100, f"levels.{name}")
    if any(levels["overdue"] >= levels[name] for name in LEVEL_KEYS - {"overdue"}):
        raise ValueError("overdue must outrank every other level")
    if any(levels["appointment"] > levels[name] for name in ("qr", "walk_in", "late_prebooking")):
        raise ValueError("appointment must not rank below ordinary tickets")
    if waits["prebooking"] < config["early_minutes"] + config["grace_minutes"]:
        raise ValueError("prebooking max wait must cover the full appointment window")
    return config


@lru_cache
def load_priority_config() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[3] / "config" / "priority.yaml"
    return validate_priority_config(json.loads(path.read_text(encoding="utf-8")))


def early_minutes() -> int:
    return int(load_priority_config()["early_minutes"])


def priority_sql(alias: str = "t") -> str:
    if alias not in {"t", "candidate"}:
        raise ValueError("unsupported SQL alias")
    return f"""
        CASE
          WHEN {alias}.source = 'walk_in'
            AND {alias}.eligible_at <= statement_timestamp() - make_interval(mins => :walk_wait)
            THEN CAST(:overdue AS integer)
          WHEN {alias}.source = 'qr'
            AND {alias}.eligible_at <= statement_timestamp() - make_interval(mins => :qr_wait)
            THEN CAST(:overdue AS integer)
          WHEN {alias}.source = 'prebooking'
            AND {alias}.eligible_at <= statement_timestamp() - make_interval(mins => :pre_wait)
            THEN CAST(:overdue AS integer)
          WHEN {alias}.source = 'prebooking'
            AND statement_timestamp() <= {alias}.scheduled_time + make_interval(mins => :grace)
            THEN CAST(:appointment AS integer)
          WHEN {alias}.source = 'prebooking' THEN CAST(:late_prebooking AS integer)
          WHEN {alias}.source = 'qr' THEN CAST(:qr_level AS integer)
          ELSE CAST(:walk_level AS integer)
        END
    """


def bind_priority_sql(template: str, alias: str) -> str:
    marker = "/* PRIORITY_EXPRESSION */"
    if template.count(marker) != 1:
        raise ValueError("priority SQL template must contain exactly one marker")
    return template.replace(marker, priority_sql(alias))


def priority_parameters(config: Mapping[str, Any]) -> dict[str, int]:
    levels = config["levels"]
    waits = config["max_wait_minutes"]
    return {
        "walk_wait": int(waits["walk_in"]),
        "qr_wait": int(waits["qr"]),
        "pre_wait": int(waits["prebooking"]),
        "grace": int(config["grace_minutes"]),
        "overdue": int(levels["overdue"]),
        "appointment": int(levels["appointment"]),
        "late_prebooking": int(levels["late_prebooking"]),
        "qr_level": int(levels["qr"]),
        "walk_level": int(levels["walk_in"]),
    }


def effective_priority(
    *, source: str, eligible_at: datetime, scheduled_time: datetime | None,
    now: datetime, config: Mapping[str, Any],
) -> int:
    waits = config["max_wait_minutes"]
    levels = config["levels"]
    if source not in WAIT_KEYS:
        raise ValueError(f"unsupported ticket source: {source}")
    if eligible_at <= now - timedelta(minutes=int(waits[source])):
        return int(levels["overdue"])
    if source == "prebooking":
        if scheduled_time is None:
            raise ValueError("prebooking requires scheduled_time")
        if now <= scheduled_time + timedelta(minutes=int(config["grace_minutes"])):
            return int(levels["appointment"])
        return int(levels["late_prebooking"])
    return int(levels["qr"] if source == "qr" else levels["walk_in"])


def queue_order_key(
    ticket: Mapping[str, Any], *, now: datetime, config: Mapping[str, Any],
) -> tuple[Any, ...]:
    return (
        effective_priority(
            source=ticket["source"],
            eligible_at=ticket["eligible_at"],
            scheduled_time=ticket.get("scheduled_time"),
            now=now,
            config=config,
        ),
        ticket["eligible_at"],
        ticket["queue_sequence"],
        ticket["id"],
    )
