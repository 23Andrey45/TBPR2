# workers/trading_status_workers.py
"""
Воркеры для проверки статуса торгов.
"""

from __future__ import annotations

from typing import Any, List
from PyQt6 import QtCore

from core.sandbox_trading_api import get_trading_status, TradingStatusInfo


class TradingStatusLoader(QtCore.QObject):
    """
    Воркер для проверки статуса торгов по списку FIGI.

    Signals:
        loaded: dict[str, TradingStatusInfo] - статусы по FIGI
        error: str - ошибка
        finished: void - завершение
    """
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, figis: list[str]):
        super().__init__()
        self.token = token
        self.figis = figis

    @QtCore.pyqtSlot()
    def run(self):
        # print(f"[TradingStatusLoader] run: {len(self.figis)} figis")
        try:
            statuses = {}
            for i, figi in enumerate(self.figis):
                try:
                    # print(f"[TradingStatusLoader] checking {figi} ({i + 1}/{len(self.figis)})")
                    status = get_trading_status(self.token, figi=figi)
                    statuses[figi] = {
                        'trading_status': status.trading_status,
                        'api_trade_available': status.api_trade_available,
                        'market_order_available': status.market_order_available,
                        'limit_order_available': status.limit_order_available,
                        'ticker': status.ticker,
                    }
                    # print(f"[TradingStatusLoader] {figi}: {status.trading_status}")
                except Exception as e:
                    # Игнорируем ошибки по отдельным FIGI
                    # print(f"[TradingStatusLoader] {figi} ERROR: {e}")
                    statuses[figi] = {
                        'error': str(e),
                        'trading_status': 'UNKNOWN',
                        'api_trade_available': False,
                        'market_order_available': False,
                        'limit_order_available': False,
                        'ticker': figi,
                    }

            # print(f"[TradingStatusLoader] loaded {len(statuses)} statuses, emitting")
            self.loaded.emit(statuses)
        except Exception as e:
            import traceback
            # print(f"[TradingStatusLoader] ERROR: {e}")
            traceback.print_exc()
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()
