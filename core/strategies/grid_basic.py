# core/strategies/grid_basic.py
from __future__ import annotations

from core.strategies.base import Strategy, ParamSpec, StrategyResult, StrategyContext
from core.trading_logic import simulate_grid


class GridBasicStrategy(Strategy):
    @property
    def strategy_id(self) -> str:
        return "grid_basic"

    @property
    def strategy_name(self) -> str:
        return "Grid: базовая (шорт разрешён)"

    def param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec("step", "Шаг сетки (0.01 = 1%)", "float", 0.01, min=0.0001, max=0.5),
            ParamSpec("lot", "Размер сделки (лоты)", "int", 1, min=1, max=1_000_000),
        ]

    def run(self, candles, params: dict, context: StrategyContext) -> StrategyResult:
        res = simulate_grid(candles, step=params["step"], lot=params["lot"])

        metrics = {
            "Свечей": str(len(candles)),
            "Сделок всего": str(len(res.trades)),
            "Покупок": str(res.buys),
            "Продаж": str(res.sells),
            "Cash (баланс денег)": f"{res.cash:.4f}",
            "Финальная позиция (лоты)": str(res.position),
            "Equity / прибыль": f"{res.equity:.4f}",
            "Макс. позиция (лоты)": str(res.max_pos),
            "Мин. позиция (лоты)": str(res.min_pos),
            "Макс. вложение (денег)": f"{max(0.0, -res.min_cash):.4f}",
        }

        return StrategyResult(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            params_used=params,
            metrics=metrics,
            extra={"trades": res.trades},
        )
