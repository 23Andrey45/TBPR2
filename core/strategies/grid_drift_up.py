from __future__ import annotations

from core.strategies.base import Strategy, ParamSpec, StrategyResult, StrategyContext
from core.trading_logic import CandleData, Trade
from core.dividends_calc import calc_paid_dividends_in_range


def _years_between(t0, t1) -> float:
    # t0/t1 обычно datetime с tzinfo
    if hasattr(t0, "timestamp") and hasattr(t1, "timestamp"):
        dt = (t1 - t0).total_seconds()
        return dt / (365.0 * 24.0 * 3600.0)
    return 0.0


def _simulate_grid_with_drift(
    candles: list[CandleData],
    *,
    step: float,
    annual_drift: float,
    trade_lots: int,
    lot_size: int,
) -> dict:
    """
    Сетка как базовая, но с дрейфом вверх:
      last_trade_price *= (1 + annual_drift)^(dt_years)
    делаем 1 раз на свечу перед обработкой сегментов.
    """
    if not candles:
        raise ValueError("Нет свечей")

    step = float(step)
    annual_drift = float(annual_drift)
    trade_lots = int(trade_lots)
    lot_size = int(lot_size or 1)

    if step <= 0:
        raise ValueError("step должно быть > 0")
    if trade_lots <= 0:
        raise ValueError("trade_lots должно быть > 0")

    trades: list[Trade] = []
    cash = 0.0
    position_lots = 0
    buys = 0
    sells = 0

    max_pos = 0
    min_pos = 0
    min_cash = 0.0
    max_cash = 0.0

    # стартовая покупка по open
    first = candles[0]
    last_trade_price = first.open

    cash -= last_trade_price * (trade_lots * lot_size)
    position_lots += trade_lots
    buys += trade_lots
    trades.append(Trade(time=first.time, side="BUY", price=last_trade_price, pos_after=position_lots))

    max_pos = max(max_pos, position_lots)
    min_pos = min(min_pos, position_lots)
    min_cash = min(min_cash, cash)
    max_cash = max(max_cash, cash)

    def process_down_segment(t, a: float, b: float):
        nonlocal cash, position_lots, last_trade_price, buys, max_pos, min_pos, min_cash, max_cash
        seg_lo, seg_hi = b, a
        while True:
            level = last_trade_price * (1.0 - step)
            if not (seg_lo <= level <= seg_hi):
                break

            cash -= level * (trade_lots * lot_size)
            position_lots += trade_lots
            last_trade_price = level
            buys += trade_lots
            trades.append(Trade(time=t, side="BUY", price=level, pos_after=position_lots))

            max_pos = max(max_pos, position_lots)
            min_pos = min(min_pos, position_lots)
            min_cash = min(min_cash, cash)
            max_cash = max(max_cash, cash)

    def process_up_segment(t, a: float, b: float):
        nonlocal cash, position_lots, last_trade_price, sells, max_pos, min_pos, min_cash, max_cash
        seg_lo, seg_hi = a, b
        while True:
            level = last_trade_price * (1.0 + step)
            if not (seg_lo <= level <= seg_hi):
                break

            cash += level * (trade_lots * lot_size)
            position_lots -= trade_lots  # как и в базовой: шорт допускается
            last_trade_price = level
            sells += trade_lots
            trades.append(Trade(time=t, side="SELL", price=level, pos_after=position_lots))

            max_pos = max(max_pos, position_lots)
            min_pos = min(min_pos, position_lots)
            min_cash = min(min_cash, cash)
            max_cash = max(max_cash, cash)

    # цикл по свечам
    prev_time = candles[0].time
    for i, c in enumerate(candles):
        if i > 0:
            yrs = _years_between(prev_time, c.time)
            # дрейф вверх: множитель
            drift_factor = (1.0 + annual_drift) ** yrs if yrs != 0 else 1.0
            last_trade_price *= drift_factor
            prev_time = c.time

        o, h, l, cl = c.open, c.high, c.low, c.close
        path = [o, h, l, cl] if cl >= o else [o, l, h, cl]

        for p0, p1 in zip(path, path[1:]):
            if p1 > p0:
                process_up_segment(c.time, p0, p1)
            elif p1 < p0:
                process_down_segment(c.time, p0, p1)

    last_price = candles[-1].close
    equity = cash + position_lots * last_price * lot_size

    return dict(
        cash=cash,
        equity=equity,
        position_lots=position_lots,
        trades=trades,
        buys=buys,
        sells=sells,
        max_pos=max_pos,
        min_pos=min_pos,
        min_cash=min_cash,
        max_cash=max_cash,
        last_price=last_price,
    )


class GridDriftUpStrategy(Strategy):
    @property
    def strategy_id(self) -> str:
        return "grid_drift_up"

    @property
    def strategy_name(self) -> str:
        return "Grid: дрейф вверх (+годовой рост)"

    def param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec("step", "Шаг сетки (0.01 = 1%)", "float", 0.01, min=0.0001, max=0.5),
            ParamSpec("annual_drift", "Ожидаемый рост в год (0.10=10%)", "float", 0.10, min=-0.99, max=5.0),
            ParamSpec("lot", "Размер сделки (лоты)", "int", 1, min=1, max=1_000_000),
        ]

    def run(self, candles, params: dict, context: StrategyContext) -> StrategyResult:
        inst = context.instrument
        lot_size = int(getattr(inst, "lot", 1) or 1)

        sim = _simulate_grid_with_drift(
            candles,
            step=params["step"],
            annual_drift=params["annual_drift"],
            trade_lots=params["lot"],
            lot_size=lot_size,
        )

        max_invested = max(0.0, -sim["min_cash"])

        metrics = {
            "Свечей": str(len(candles)),
            "annual_drift": str(params["annual_drift"]),
            "Сделок всего": str(len(sim["trades"])),
            "Покупок (лоты)": str(sim["buys"]),
            "Продаж (лоты)": str(sim["sells"]),
            "Cash (баланс денег)": f"{sim['cash']:.4f}",
            "Equity / прибыль": f"{sim['equity']:.4f}",
            "Финальная позиция (лоты)": str(sim["position_lots"]),
            "Макс. позиция (лоты)": str(sim["max_pos"]),
            "Мин. позиция (лоты)": str(sim["min_pos"]),
            "Макс. вложение (денег)": f"{max_invested:.4f}",
        }

        return StrategyResult(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            params_used=params,
            metrics=metrics,
            extra={"trades": sim["trades"]},
        )


class GridDriftUpDividendsStrategy(Strategy):
    @property
    def strategy_id(self) -> str:
        return "grid_drift_up_div"

    @property
    def strategy_name(self) -> str:
        return "Grid: дрейф вверх + дивиденды(paid)"

    def param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec("step", "Шаг сетки (0.01 = 1%)", "float", 0.01, min=0.0001, max=0.5),
            ParamSpec("annual_drift", "Ожидаемый рост в год (0.10=10%)", "float", 0.10, min=-0.99, max=5.0),
            ParamSpec("lot", "Размер сделки (лоты)", "int", 1, min=1, max=1_000_000),
        ]

    def run(self, candles, params: dict, context: StrategyContext) -> StrategyResult:
        inst = context.instrument
        kind = (getattr(inst, "kind", "") or "").lower()
        lot_size = int(getattr(inst, "lot", 1) or 1)

        sim = _simulate_grid_with_drift(
            candles,
            step=params["step"],
            annual_drift=params["annual_drift"],
            trade_lots=params["lot"],
            lot_size=lot_size,
        )

        div_paid = 0.0
        if kind in ("share", "etf") and context.dividends and candles and hasattr(candles[0].time, "tzinfo"):
            div_res = calc_paid_dividends_in_range(
                context.dividends,
                sim["trades"],
                start_pos_lots=0,
                lot_size=lot_size,
                range_start=candles[0].time,
                range_end=candles[-1].time,
            )
            div_paid = div_res.paid

        equity_with_div = sim["equity"] + div_paid
        max_invested = max(0.0, -sim["min_cash"])

        metrics = {
            "Свечей": str(len(candles)),
            "annual_drift": str(params["annual_drift"]),
            "Equity (без див)": f"{sim['equity']:.4f}",
            "Дивиденды (paid)": f"{div_paid:.4f}",
            "Equity (с див)": f"{equity_with_div:.4f}",
            "Сделок": str(len(sim["trades"])),
            "Финальная позиция (лоты)": str(sim["position_lots"]),
            "Макс. позиция (лоты)": str(sim["max_pos"]),
            "Мин. позиция (лоты)": str(sim["min_pos"]),
            "Макс. вложение (денег)": f"{max_invested:.4f}",
        }

        return StrategyResult(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            params_used=params,
            metrics=metrics,
            extra={"trades": sim["trades"]},
        )
    