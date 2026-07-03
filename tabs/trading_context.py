# tabs/trading_context.py
from __future__ import annotations

from PyQt6 import QtCore


class TradingContext(QtCore.QObject):
    account_changed = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._account_id = ""

    @property
    def account_id(self) -> str:
        return self._account_id

    def set_account_id(self, account_id: str):
        account_id = (account_id or "").strip()
        if account_id == self._account_id:
            return
        self._account_id = account_id
        self.account_changed.emit(self._account_id)