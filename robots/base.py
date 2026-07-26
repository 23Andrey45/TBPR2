# core/robots/base.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GridRobot:
    robot_id: str
    robot_type: str
    instrument_kind: str
    instrument_ticker: str
    instrument_name: str
    instrument_isin: str
    instrument_figi: str
    start_price: float
    step_pct: float
    steps_down: int
    steps_up: int
    last_trade_price: float
    current_price: float
    status: str
    created_at: str