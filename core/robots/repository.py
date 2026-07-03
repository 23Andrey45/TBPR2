# core/robots/repository.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

ROBOTS_FILE = DATA_DIR / "robots_cache.json"


def load_robots() -> list[dict[str, Any]]:
    path = Path(ROBOTS_FILE)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("robots", [])
    return [x for x in items if isinstance(x, dict)]


def save_robots(robots: list[dict[str, Any]]) -> None:
    path = Path(ROBOTS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"robots": robots}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")