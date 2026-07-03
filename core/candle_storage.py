# core/candle_storage.py

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from core.trading_logic import CandleData


def _time_to_str(t) -> str:
    if hasattr(t, "isoformat"):
        return t.isoformat()
    return str(t)


def _str_to_time(s: str):
    # Пытаемся восстановить datetime, если это ISO-строка
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return s  # оставляем строкой


def save_candles_csv(path: str | Path, candles: list[CandleData]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([
                _time_to_str(c.time),
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume,
            ])


def load_candles_csv(path: str | Path) -> list[CandleData]:
    path = Path(path)
    candles: list[CandleData] = []

    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            candles.append(
                CandleData(
                    time=_str_to_time(row["time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(float(row["volume"])),  # на всякий случай
                )
            )
    return candles
