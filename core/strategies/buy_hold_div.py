from __future__ import annotations

from core.strategies.base import Strategy, ParamSpec, StrategyResult, StrategyContext
from core.dividends_calc import calc_paid_dividends_in_range
from core.trading_logic import Trade


class BuyHoldDividendsStrategy(Strategy):
    @property
    def strategy_id(self) -> str:
        return "buy_hold_div"

    @property
    def strategy_name(self) -> str:
        return "Buy&Hold + дивиденды(paid)"

    def param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec("lot", "Покупка на старте (лоты)", "int", 1, min=1, max=1_000_000),
        ]

    def run(self, candles, params: dict, context: StrategyContext) -> StrategyResult:
        if not candles:
            raise ValueError("Нет свечей")

        lots = params["lot"]
        p0 = candles[0].open
        p1 = candles[-1].close

        cash = -p0 * lots
        equity = cash + lots * p1

        inst = context.instrument
        kind = (getattr(inst, "kind", "") or "").lower()
        lot_size = int(getattr(inst, "lot", 1) or 1)

        div_paid = 0.0
        if kind in ("share", "etf") and context.dividends:
            if hasattr(candles[0].time, "tzinfo"):
                trades = [Trade(time=candles[0].time, side="BUY", price=p0, pos_after=lots)]
                div_res = calc_paid_dividends_in_range(
                    context.dividends,
                    trades,
                    start_pos_lots=0,
                    lot_size=lot_size,
                    range_start=candles[0].time,
                    range_end=candles[-1].time,
                )
                div_paid = div_res.paid

        equity_with_div = equity + div_paid
        max_invested = p0 * lots  # одна покупка на старте

        metrics = {
            "Свечей": str(len(candles)),
            "Buy price (open first)": f"{p0:.6f}",
            "Last price (close last)": f"{p1:.6f}",

            "Equity (без див)": f"{equity:.4f}",
            "Дивиденды (paid)": f"{div_paid:.4f}",
            "Equity (с див)": f"{equity_with_div:.4f}",

            "Финальная позиция (лоты)": str(lots),
            "Макс. позиция (лоты)": str(lots),
            "Мин. позиция (лоты)": str(lots),

            "Финальная позиция (бумаг)": str(lots * lot_size),
            "Макс. позиция (бумаг)": str(lots * lot_size),
            "Мин. позиция (бумаг)": str(lots * lot_size),

            "Макс. вложение (денег)": f"{max_invested:.4f}",
        }

        return StrategyResult(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            params_used=params,
            metrics=metrics,
        )
    