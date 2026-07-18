# tabs/workers_legacy.py
# СТАРЫЙ ФАЙЛ - НЕ ИСПОЛЬЗОВАТЬ!
# Воркеры перенесены в workers/
# Этот файл оставлен для совместимости

# Импортируем из нового места для обратной совместимости
from workers import (
    SandboxAccountsLoader,
    SandboxMoneyBalanceLoader,
    SandboxPostLimitOrderLoader,
    SandboxActiveOrdersLoader,
    CancelSandboxOrderWorker,
    RecentDealsLoader,
    OrderStatesLoader,
)

# Остальные воркеры которые используются другими вкладками
import asyncio
import traceback
from datetime import datetime
import threading
from queue import Queue, Empty

from PyQt6 import QtCore
from t_tech.invest import CandleInterval

from core.trading_logic import iter_candles, CandleData
from core.account_api import fetch_sandbox_accounts, fetch_money_balance
from core.instruments_catalog import fetch_available_shares
from core.sandbox_trading_api import try_post_sandbox_market_order, get_sandbox_portfolio


class CandleLoader(QtCore.QObject):
    candle_received = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)

    def __init__(self, token: str, instrument_id: str, from_: datetime, interval: CandleInterval, parent=None):
        super().__init__(parent)
        self.token = token
        self.instrument_id = instrument_id
        self.from_ = from_
        self.interval = interval
        self._stop = False

    def stop(self):
        self._stop = True

    @QtCore.pyqtSlot()
    def run(self):
        try:
            asyncio.run(self._work())
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()

    async def _work(self):
        print("[candles] start loading...")
        n = 0
        async for c in iter_candles(token=self.token, instrument_id=self.instrument_id, from_=self.from_, interval=self.interval):
            if self._stop:
                print("[candles] stopped by user")
                break
            self.candle_received.emit(c)
            n += 1
            if n % 500 == 0:
                print(f"[candles] loaded: {n}")
        print(f"[candles] finished loading. total={n}")


class SharesLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    @QtCore.pyqtSlot()
    def run(self):
        try:
            shares = fetch_available_shares(self.token)
            self.loaded.emit(shares)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class InstrumentsCatalogLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    @QtCore.pyqtSlot()
    def run(self):
        try:
            shares = fetch_available_shares(self.token)
            bonds = fetch_available_bonds(self.token)
            etfs = fetch_available_etfs(self.token)
            self.loaded.emit({"share": shares, "bond": bonds, "etf": etfs})
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


def fetch_available_bonds(token: str):
    from core.instruments_catalog import fetch_available_bonds as _fetch
    return _fetch(token)


def fetch_available_etfs(token: str):
    from core.instruments_catalog import fetch_available_etfs as _fetch
    return _fetch(token)


class DividendsLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, figi: str, from_: datetime, to: datetime):
        super().__init__()
        self.token = token
        self.figi = figi
        self.from_ = from_
        self.to = to

    @QtCore.pyqtSlot()
    def run(self):
        try:
            from core.dividends_api import fetch_dividends
            divs = fetch_dividends(self.token, self.figi, self.from_, self.to)
            self.loaded.emit(divs)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()
