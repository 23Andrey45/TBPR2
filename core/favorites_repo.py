# core/favorites_repo.py
from __future__ import annotations

import json
from pathlib import Path

from core.instruments_catalog import InstrumentInfo


def load_favorites(path: str | Path) -> dict[str, InstrumentInfo]:
    path = Path(path)
    if not path.exists():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    favs: dict[str, InstrumentInfo] = {}
    for d in items:
        info = InstrumentInfo.from_dict(d)
        if info.kind and info.instrument_id:
            favs[info.fav_key()] = info
    return favs


def save_favorites(path: str | Path, favorites: dict[str, InstrumentInfo]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": [v.to_dict() for v in favorites.values()]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
