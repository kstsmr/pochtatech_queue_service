import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache
def load_priority_config() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[3] / "config" / "priority.yaml"
    return json.loads(path.read_text(encoding="utf-8"))


def early_minutes() -> int:
    return int(load_priority_config()["early_minutes"])
