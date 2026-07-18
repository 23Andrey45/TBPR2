# TBPR2 Workers Module
"""
Общие воркеры для всего приложения.
Все воркеры работают в отдельных QThread и не блокируют UI.
"""

# Account workers
from workers.account_workers import (
    SandboxAccountsLoader,
    SandboxMoneyBalanceLoader,
)

# Order workers
from workers.order_workers import (
    SandboxPostLimitOrderLoader,
    SandboxActiveOrdersLoader,
    CancelSandboxOrderWorker,
    RecentDealsLoader,
    OrderStatesLoader,
)

# Trading status workers
from workers.trading_status_workers import (
    TradingStatusLoader,
)

# History loader workers
from workers.history_loader_workers import (
    SandboxHistoryLoader,
)

# Instrument workers (из legacy для совместимости)
from tabs.workers_legacy import (
    InstrumentsCatalogLoader,
    CandleLoader,
    SharesLoader,
    DividendsLoader,
)

__all__ = [
    # Account workers
    'SandboxAccountsLoader',
    'SandboxMoneyBalanceLoader',

    # Order workers
    'SandboxPostLimitOrderLoader',
    'SandboxActiveOrdersLoader',
    'CancelSandboxOrderWorker',
    'RecentDealsLoader',
    'OrderStatesLoader',

    # Trading status workers
    'TradingStatusLoader',

    # History loader workers
    'SandboxHistoryLoader',

    # Instrument workers
    'InstrumentsCatalogLoader',
    'CandleLoader',
    'SharesLoader',
    'DividendsLoader',
]

print("[WORKERS] Module loaded successfully")
