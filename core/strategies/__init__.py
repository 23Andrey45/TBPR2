# core/strategies/__init__.py
from core.strategies.base import Strategy
from core.strategies.grid_basic import GridBasicStrategy
from core.strategies.grid_basic_div import GridBasicDividendsStrategy
from core.strategies.buy_hold_div import BuyHoldDividendsStrategy
from core.strategies.sma_cross import SmaCrossStrategy
from core.strategies.grid_atr_adaptive import GridAtrAdaptiveStrategy, GridAtrAdaptiveDividendsStrategy
from core.strategies.grid_drift_up import GridDriftUpStrategy, GridDriftUpDividendsStrategy
from core.strategies.grid_dense_delayed_sell import (GridDenseDelayedSellStrategy,GridDenseDelayedSellDividendsStrategy,
)

STRATEGIES = [
    GridBasicStrategy(),
    GridBasicDividendsStrategy(),
    GridAtrAdaptiveStrategy(),
    GridAtrAdaptiveDividendsStrategy(),
    GridDriftUpStrategy(),
    GridDriftUpDividendsStrategy(),
    BuyHoldDividendsStrategy(),
    SmaCrossStrategy(),
    GridDenseDelayedSellStrategy(),
    GridDenseDelayedSellDividendsStrategy(),
]

def get_strategy(strategy_id: str) -> Strategy:
    for s in STRATEGIES:
        if s.strategy_id == strategy_id:
            return s
    raise KeyError(strategy_id)
