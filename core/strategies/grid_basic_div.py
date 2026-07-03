from __future__ import annotations

from core.strategies.base import Strategy, ParamSpec, StrategyResult, StrategyContext
from core.trading_logic import simulate_grid
from core.dividends_calc import calc_paid_dividends_in_range


class GridBasicDividendsStrategy(Strategy):
    @property
    def strategy_id(self) -> str:
        return "grid_basic_div"

    @property
    def strategy_name(self) -> str:
        return "Grid: базовая + дивиденды(paid)"

    def param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec("step", "Шаг сетки (0.01 = 1%)", "float", 0.01, min=0.0001, max=0.5),
            ParamSpec("lot", "Размер сделки (лоты)", "int", 1, min=1, max=1_000_000),
        ]

    def run(self, candles, params: dict, context: StrategyContext) -> StrategyResult:
        base = simulate_grid(candles, step=params["step"], lot=params["lot"])

        inst = context.instrument
        kind = (getattr(inst, "kind", "") or "").lower()
        lot_size = int(getattr(inst, "lot", 1) or 1)

        div_paid = 0.0
        if kind in ("share", "etf") and context.dividends and candles:
            if hasattr(candles[0].time, "tzinfo"):
                div_res = calc_paid_dividends_in_range(
                    context.dividends,
                    base.trades,
                    start_pos_lots=0,
                    lot_size=lot_size,
                    range_start=candles[0].time,
                    range_end=candles[-1].time,
                )
                div_paid = div_res.paid

        equity_with_div = base.equity + div_paid

        metrics = {
            "Свечей": str(len(candles)),
            "Сделок всего": str(len(base.trades)),
            "Покупок": str(base.buys),
            "Продаж": str(base.sells),

            "Cash (баланс денег)": f"{base.cash:.4f}",
            "Equity (без див)": f"{base.equity:.4f}",
            "Дивиденды (paid)": f"{div_paid:.4f}",
            "Equity (с див)": f"{equity_with_div:.4f}",

            "Финальная позиция (лоты)": str(base.position),
            "Макс. позиция (лоты)": str(base.max_pos),
            "Мин. позиция (лоты)": str(base.min_pos),

            "Финальная позиция (бумаг)": str(base.position * lot_size),
            "Макс. позиция (бумаг)": str(base.max_pos * lot_size),
            "Мин. позиция (бумаг)": str(base.min_pos * lot_size),

            "Макс. вложение (денег)": f"{max(0.0, -base.min_cash):.4f}",
        }

        return StrategyResult(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            params_used=params,
            metrics=metrics,
            extra={"trades": base.trades},
        )
