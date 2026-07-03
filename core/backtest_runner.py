# core/backtest_runner.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from core.strategies.base import Strategy, StrategyResult, StrategyContext


@dataclass
class BacktestRunner:
    strategies: list[Strategy]

    def run_one(
        self,
        candles,
        strategy_id: str,
        user_params: Optional[dict[str, Any]] = None,
        context: Optional[StrategyContext] = None,
    ) -> StrategyResult:
        s = next(x for x in self.strategies if x.strategy_id == strategy_id)
        params = s.normalize_params(user_params)
        return s.run(candles, params, context or StrategyContext())

    def run_all(
        self,
        candles,
        params_by_strategy: Optional[dict[str, dict[str, Any]]] = None,
        context: Optional[StrategyContext] = None,
    ) -> dict[str, StrategyResult]:
        params_by_strategy = params_by_strategy or {}
        out: dict[str, StrategyResult] = {}
        ctx = context or StrategyContext()

        for s in self.strategies:
            user_params = params_by_strategy.get(s.strategy_id)
            params = s.normalize_params(user_params)
            out[s.strategy_id] = s.run(candles, params, ctx)

        return out
    