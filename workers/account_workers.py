# workers/account_workers.py
"""
Воркеры для работы с аккаунтами и балансом.
Используются во всём приложении (Торговля, Роботы, и т.д.)
"""

from __future__ import annotations

import traceback
from PyQt6 import QtCore

from core.sandbox_api import (
    list_sandbox_accounts,
    get_money_balance,
)


class SandboxAccountsLoader(QtCore.QObject):
    """
    Воркер для загрузки sandbox аккаунтов.

    Signals:
        loaded: list[SandboxAccountInfo] - список аккаунтов
        error: str - ошибка
        finished: void - завершение
    """
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    @QtCore.pyqtSlot()
    def run(self):
        try:
            accounts = list_sandbox_accounts(self.token)
            self.loaded.emit(accounts)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class SandboxMoneyBalanceLoader(QtCore.QObject):
    """
    Воркер для загрузки денежного баланса аккаунта.

    Signals:
        loaded: list[MoneyRow] - список балансов по валютам
        error: str - ошибка
        finished: void - завершение
    """
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str):
        super().__init__()
        self.token = token
        self.account_id = account_id

    @QtCore.pyqtSlot()
    def run(self):
        try:
            rows = get_money_balance(self.token, self.account_id)
            self.loaded.emit(rows)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()
