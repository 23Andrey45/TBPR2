# core/trading_logic.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

from t_tech.invest import AsyncClient, CandleInterval

# CandleSourceType может отсутствовать/не реэкспортироваться в вашей версии.
try:
    from t_tech.invest.grpc.marketdata_pb2 import CandleSourceType  # type: ignore
except Exception:  # pragma: no cover
    CandleSourceType = None  # noqa: N816


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def quotation_to_float(q) -> float:
    return float(q.units) + float(q.nano) / 1e9


@dataclass(frozen=True)
class CandleData:
    time: object
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class Trade:
    time: object
    side: str   # "BUY" / "SELL"
    price: float
    pos_after: int


@dataclass(frozen=True)
class GridResult:
    cash: float
    position: int
    last_price: float
    equity: float
    trades: list[Trade]
    buys: int
    sells: int
    max_pos: int
    min_pos: int
    min_cash: float
    max_cash: float


async def iter_candles(
    token: str,
    instrument_id: str,
    from_: datetime,
    interval: CandleInterval,
) -> AsyncIterator[CandleData]:
    """
    Асинхронный генератор свечей.
    UI может подписаться и получать свечи потоково.
    Здесь нет PyQt и сигналов.
    """
    async with AsyncClient(token) as client:
        base_kwargs = dict(
            instrument_id=instrument_id,
            from_=from_,
            interval=interval,
        )

        # Пробуем вызвать с candle_source_type, если доступно. Если сигнатура не поддерживает — без него.
        if CandleSourceType is not None:
            try:
                async for candle in client.get_all_candles(
                    **base_kwargs,
                    candle_source_type=CandleSourceType.CANDLE_SOURCE_EXCHANGE,
                ):
                    yield CandleData(
                        time=candle.time,
                        open=quotation_to_float(candle.open),
                        high=quotation_to_float(candle.high),
                        low=quotation_to_float(candle.low),
                        close=quotation_to_float(candle.close),
                        volume=int(candle.volume),
                    )
                return
            except TypeError:
                pass  # параметр не поддерживается в этой версии

        async for candle in client.get_all_candles(**base_kwargs):
            yield CandleData(
                time=candle.time,
                open=quotation_to_float(candle.open),
                high=quotation_to_float(candle.high),
                low=quotation_to_float(candle.low),
                close=quotation_to_float(candle.close),
                volume=int(candle.volume),
            )


def simulate_grid(candles: list[CandleData], step: float = 0.01, lot: int = 1) -> GridResult:
    if not candles:
        raise ValueError("Нет свечей для расчёта")

    trades: list[Trade] = []
    cash = 0.0
    position = 0
    buys = 0
    sells = 0
    max_pos = 0
    min_pos = 0

    min_cash = cash
    max_cash = cash

    first = candles[0]
    last_trade_price = first.open

    # BUY 1 лот на старте
    cash -= last_trade_price * lot
    position += lot
    buys += 1
    trades.append(Trade(time=first.time, side="BUY", price=last_trade_price, pos_after=position))

    max_pos = max(max_pos, position)
    min_pos = min(min_pos, position)
    min_cash = min(min_cash, cash)
    max_cash = max(max_cash, cash)

    def next_buy(p: float) -> float:
        return p * (1.0 - step)

    def next_sell(p: float) -> float:
        return p * (1.0 + step)

    def process_down_segment(t, a: float, b: float):
        nonlocal cash, position, last_trade_price, buys, max_pos, min_pos, min_cash, max_cash
        seg_lo, seg_hi = b, a  # a>b
        while True:
            level = next_buy(last_trade_price)
            if not (seg_lo <= level <= seg_hi):
                break

            cash -= level * lot
            position += lot
            last_trade_price = level
            buys += 1
            trades.append(Trade(time=t, side="BUY", price=level, pos_after=position))

            max_pos = max(max_pos, position)
            min_pos = min(min_pos, position)
            min_cash = min(min_cash, cash)
            max_cash = max(max_cash, cash)

    def process_up_segment(t, a: float, b: float):
        nonlocal cash, position, last_trade_price, sells, max_pos, min_pos, min_cash, max_cash
        seg_lo, seg_hi = a, b  # b>a
        while True:
            level = next_sell(last_trade_price)
            if not (seg_lo <= level <= seg_hi):
                break

            cash += level * lot
            position -= lot
            last_trade_price = level
            sells += 1
            trades.append(Trade(time=t, side="SELL", price=level, pos_after=position))

            max_pos = max(max_pos, position)
            min_pos = min(min_pos, position)
            min_cash = min(min_cash, cash)
            max_cash = max(max_cash, cash)

    for c in candles:
        o, h, l, cl = c.open, c.high, c.low, c.close
        path = [o, h, l, cl] if cl >= o else [o, l, h, cl]

        for p0, p1 in zip(path, path[1:]):
            if p1 > p0:
                process_up_segment(c.time, p0, p1)
            elif p1 < p0:
                process_down_segment(c.time, p0, p1)

    last_price = candles[-1].close
    equity = cash + position * last_price

    return GridResult(
        cash=cash,
        position=position,
        last_price=last_price,
        equity=equity,
        trades=trades,
        buys=buys,
        sells=sells,
        max_pos=max_pos,
        min_pos=min_pos,
        min_cash=min_cash,
        max_cash=max_cash,
    )