# core/dividends_calc.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.dividends_api import DividendEvent
from core.trading_logic import Trade


@dataclass(frozen=True)
class DividendPaidResult:
    paid: float
    currency: str


def position_lots_at_end_of_date(trades: list[Trade], start_pos_lots: int, cutoff_date) -> int:
    pos = start_pos_lots
    trades_sorted = sorted(trades, key=lambda x: x.time)

    for tr in trades_sorted:
        t = tr.time
        if hasattr(t, "date") and t.date() <= cutoff_date:
            pos = int(tr.pos_after)
        else:
            if hasattr(t, "date"):
                break
    return pos


def calc_paid_dividends_in_range(
    dividends: list[DividendEvent],
    trades: list[Trade],
    *,
    start_pos_lots: int,
    lot_size: int,
    range_start: datetime,
    range_end: datetime,
) -> DividendPaidResult:
    """
    Считаем ТОЛЬКО дивиденды, у которых payment_date попадает в [range_start, range_end].
    Кол-во бумаг берём на конец last_buy_date.
    """
    if not dividends:
        return DividendPaidResult(paid=0.0, currency="")

    lot_size = int(lot_size or 1)
    paid = 0.0
    currency = dividends[0].currency

    for d in dividends:
        if not (range_start <= d.payment_date <= range_end):
            continue

        cutoff = d.last_buy_date.date()
        pos_lots = position_lots_at_end_of_date(trades, start_pos_lots, cutoff)
        qty_shares = pos_lots * lot_size

        paid += qty_shares * d.dividend_net_per_share

    return DividendPaidResult(paid=paid, currency=currency)
