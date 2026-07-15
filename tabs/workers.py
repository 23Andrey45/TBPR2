# tabs/workers.py
# Здесь лежат Qt-воркеры (потоки/загрузчики). Это часть UI-слоя,
# но вынесенная из конкретной вкладки.

import asyncio
import traceback
from datetime import datetime
import threading
from queue import Queue, Empty

from PyQt6 import QtCore
from t_tech.invest import CandleInterval

from core.trading_logic import iter_candles, CandleData

# from core.account_api import fetch_accounts, fetch_money_balance

from core.account_api import fetch_sandbox_accounts, fetch_money_balance

import traceback
from PyQt6 import QtCore

from core.sandbox_orders_api import (
    try_post_sandbox_limit_order,
    list_active_sandbox_orders,
)

from core.instruments_catalog import fetch_available_shares

from core.sandbox_trading_api import try_post_sandbox_market_order, get_sandbox_portfolio


class CandleLoader(QtCore.QObject):
    candle_received = QtCore.pyqtSignal(object)  # CandleData
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)  # traceback

    def __init__(
        self,
        token: str,
        instrument_id: str,
        from_: datetime,
        interval: CandleInterval,
        parent=None,
    ):
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

        async for c in iter_candles(
            token=self.token,
            instrument_id=self.instrument_id,
            from_=self.from_,
            interval=self.interval,
        ):
            if self._stop:
                print("[candles] stopped by user")
                break

            self.candle_received.emit(c)
            n += 1
            if n % 500 == 0:
                print(f"[candles] loaded: {n}")

        print(f"[candles] finished loading. total={n}")


class SharesLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # list[ShareInfo]
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


class AccountsLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # list[AccountInfo]
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    @QtCore.pyqtSlot()
    def run(self):
        try:
            # self.loaded.emit(fetch_accounts(self.token))
            self.loaded.emit(fetch_sandbox_accounts(self.token))
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class MoneyBalanceLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # list[MoneyRow]
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str):
        super().__init__()
        self.token = token
        self.account_id = account_id

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.loaded.emit(fetch_money_balance(self.token, self.account_id))
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


import traceback
from PyQt6 import QtCore

from core.sandbox_api import (
    list_sandbox_accounts,
    open_sandbox_account,
    sandbox_pay_in,
    get_money_balance,
)


class SandboxAccountsLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # list[SandboxAccountInfo]
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.loaded.emit(list_sandbox_accounts(self.token))
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class SandboxOpenAccountLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # account_id (str)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.loaded.emit(open_sandbox_account(self.token))
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class SandboxPayInLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal()  # ok
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, currency: str, units: int):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.currency = currency
        self.units = units

    @QtCore.pyqtSlot()
    def run(self):
        try:
            sandbox_pay_in(self.token, self.account_id, self.currency, self.units)
            self.loaded.emit()
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class SandboxMoneyBalanceLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # list[MoneyRow]
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str):
        super().__init__()
        self.token = token
        self.account_id = account_id

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.loaded.emit(get_money_balance(self.token, self.account_id))
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


# --- sandbox trading workers ---

import traceback
from PyQt6 import QtCore


class SandboxPostMarketOrderLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # OrderResult
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, instrument_id: str, figi: str, uid: str, direction: str, lots: int):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.instrument_id = instrument_id
        self.figi = figi
        self.uid = uid
        self.direction = direction
        self.lots = lots

    @QtCore.pyqtSlot()
    def run(self):
        try:
            res = try_post_sandbox_market_order(
                self.token,
                self.account_id,
                instrument_id=self.instrument_id,
                figi=self.figi,
                uid=self.uid,
                direction=self.direction,
                lots=self.lots,
            )
            self.loaded.emit(res)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class SandboxPortfolioLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # list[PortfolioRow]
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str):
        super().__init__()
        self.token = token
        self.account_id = account_id

    @QtCore.pyqtSlot()
    def run(self):
        try:
            rows = get_sandbox_portfolio(self.token, self.account_id)
            self.loaded.emit(rows)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class SandboxPostLimitOrderLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # PlaceOrderAttempt
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    REQUEST_TIMEOUT_SEC = 12.0

    def __init__(self, token: str, account_id: str, figi: str, direction: str, lots: int, price_str: str):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.figi = figi
        self.direction = direction
        self.lots = lots
        self.price_str = price_str

    @QtCore.pyqtSlot()
    def run(self):
        try:
            result_queue: Queue = Queue(maxsize=1)

            def _task():
                try:
                    res = try_post_sandbox_limit_order(
                        self.token,
                        self.account_id,
                        figi=self.figi,
                        direction=self.direction,
                        lots=self.lots,
                        price_str=self.price_str,
                    )
                    result_queue.put((res, None))
                except Exception:
                    result_queue.put((None, traceback.format_exc()))

            t = threading.Thread(target=_task, daemon=True)
            t.start()
            t.join(timeout=self.REQUEST_TIMEOUT_SEC)

            if t.is_alive():
                self.error.emit(f"SandboxPostLimitOrderLoader timeout after {self.REQUEST_TIMEOUT_SEC:.1f}s")
                return

            try:
                res, err = result_queue.get_nowait()
            except Empty:
                self.error.emit("SandboxPostLimitOrderLoader empty result")
                return

            if err:
                self.error.emit(err)
                return

            self.loaded.emit(res)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class SandboxActiveOrdersLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # list[ActiveOrder]
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    REQUEST_TIMEOUT_SEC = 8.0

    def __init__(self, token: str, account_id: str):
        super().__init__()
        self.token = token
        self.account_id = account_id

    @QtCore.pyqtSlot()
    def run(self):
        try:
            result_queue: Queue = Queue(maxsize=1)

            def _task():
                try:
                    res = list_active_sandbox_orders(self.token, self.account_id)
                    result_queue.put((res, None))
                except Exception:
                    result_queue.put((None, traceback.format_exc()))

            t = threading.Thread(target=_task, daemon=True)
            t.start()
            t.join(timeout=self.REQUEST_TIMEOUT_SEC)

            if t.is_alive():
                self.error.emit(f"SandboxActiveOrdersLoader timeout after {self.REQUEST_TIMEOUT_SEC:.1f}s")
                return

            try:
                res, err = result_queue.get_nowait()
            except Empty:
                self.error.emit("SandboxActiveOrdersLoader empty result")
                return

            if err:
                self.error.emit(err)
                return

            self.loaded.emit(res)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


from core.instruments_catalog import fetch_available_shares, fetch_available_bonds, fetch_available_etfs


class InstrumentsCatalogLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # dict: {"share": [...], "bond":[...], "etf":[...]}
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


import traceback
from PyQt6 import QtCore
from core.dividends_api import fetch_dividends


class DividendsLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # list[DividendEvent]
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, figi: str, from_, to):
        super().__init__()
        self.token = token
        self.figi = figi
        self.from_ = from_
        self.to = to

    @QtCore.pyqtSlot()
    def run(self):
        try:
            divs = fetch_dividends(self.token, figi=self.figi, from_=self.from_, to=self.to)
            self.loaded.emit(divs)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()