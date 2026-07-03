# core/candle_cache.py
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.candle_storage import load_candles_csv, save_candles_csv
from core.trading_logic import CandleData
from core.instruments_catalog import InstrumentInfo


def _safe_name(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "NONAME"
    # заменяем всё кроме букв/цифр/._- на _
    return re.sub(r"[^0-9A-Za-z._-]+", "_", s)


def _interval_to_str(interval: Any) -> str:
    # CandleInterval enum обычно имеет .name
    if hasattr(interval, "name"):
        return str(interval.name)
    return _safe_name(str(interval))


def candles_cache_path(base_dir: str | Path, info: InstrumentInfo, interval: Any, days: int) -> Path:
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    ticker = _safe_name(info.ticker)
    kind = _safe_name(info.kind)

    uniq = info.isin or info.figi or info.uid or info.instrument_id
    uniq = _safe_name(uniq)

    interval_s = _interval_to_str(interval)

    filename = f"{ticker}_{kind}_{uniq}_{interval_s}_{days}d.csv"
    return base_dir / filename


def load_cached_candles(base_dir: str | Path, info: InstrumentInfo, interval: Any, days: int) -> list[CandleData] | None:
    path = candles_cache_path(base_dir, info, interval, days)
    if not path.exists():
        return None
    return load_candles_csv(path)


def save_cached_candles(base_dir: str | Path, info: InstrumentInfo, interval: Any, days: int, candles: list[CandleData]) -> Path:
    path = candles_cache_path(base_dir, info, interval, days)
    save_candles_csv(path, candles)
    return path
