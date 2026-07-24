# app/app_context.py
"""
Контекст приложения - хранит общую информацию для всех вкладок.
Все вкладки получают ссылку на этот объект и могут читать/записывать данные.
"""

from __future__ import annotations

from PyQt6 import QtCore


class AppContext(QtCore.QObject):
    """
    Контекст приложения.
    Хранит общую информацию: account_id, токены, настройки и т.д.
    """

    # Сигналы для уведомления об изменениях
    account_changed = QtCore.pyqtSignal(str)
    token_changed = QtCore.pyqtSignal(str)  # "sandbox" или "real"

    def __init__(self, parent=None):
        super().__init__(parent)

        # Токены
        self._sandbox_token: str = ""
        self._real_token: str = ""

        # Account ID
        self._account_id: str = ""
        self._real_account_id: str = ""

        # Текущий режим (False=песочница, True=реальный)
        self._is_real_account: bool = False

    # =========================================================================
    # Токены
    # =========================================================================

    @property
    def sandbox_token(self) -> str:
        """Токен песочницы."""
        return self._sandbox_token

    @sandbox_token.setter
    def sandbox_token(self, value: str):
        self._sandbox_token = value
        if not self._is_real_account:
            self.token_changed.emit("sandbox")

    @property
    def real_token(self) -> str:
        """Токен реального счёта."""
        return self._real_token

    @real_token.setter
    def real_token(self, value: str):
        self._real_token = value
        if self._is_real_account:
            self.token_changed.emit("real")

    def get_current_token(self) -> str:
        """Получить токен для текущего типа счёта."""
        return self._real_token if self._is_real_account else self._sandbox_token

    # =========================================================================
    # Account ID
    # =========================================================================

    @property
    def account_id(self) -> str:
        """Текущий account_id (в зависимости от режима)."""
        return self._real_account_id if self._is_real_account else self._account_id

    @account_id.setter
    def account_id(self, value: str):
        """Установить account_id для текущего режима."""
        if self._is_real_account:
            self._real_account_id = value
        else:
            self._account_id = value
        self.account_changed.emit(value)

    @property
    def sandbox_account_id(self) -> str:
        """Account ID песочницы."""
        return self._account_id

    @sandbox_account_id.setter
    def sandbox_account_id(self, value: str):
        self._account_id = value
        if not self._is_real_account:
            self.account_changed.emit(value)

    @property
    def real_account_id(self) -> str:
        """Account ID реального счёта."""
        return self._real_account_id

    @real_account_id.setter
    def real_account_id(self, value: str):
        self._real_account_id = value
        if self._is_real_account:
            self.account_changed.emit(value)

    # =========================================================================
    # Режим счёта
    # =========================================================================

    @property
    def is_real_account(self) -> bool:
        """True если выбран реальный счёт."""
        return self._is_real_account

    @is_real_account.setter
    def is_real_account(self, value: bool):
        self._is_real_account = value
        # Уведомляем об изменении режима
        self.token_changed.emit("real" if value else "sandbox")
        self.account_changed.emit(self.account_id)

    def switch_to_sandbox(self):
        """Переключиться на песочницу."""
        self._is_real_account = False
        self.token_changed.emit("sandbox")
        self.account_changed.emit(self._account_id)

    def switch_to_real(self):
        """Переключиться на реальный счёт."""
        self._is_real_account = True
        self.token_changed.emit("real")
        self.account_changed.emit(self._real_account_id)

    # =========================================================================
    # Информация о состоянии
    # =========================================================================

    def get_info(self) -> dict:
        """Получить информацию о состоянии контекста."""
        return {
            "sandbox_token": self._sandbox_token[:10] + "..." if self._sandbox_token else "❌",
            "real_token": self._real_token[:10] + "..." if self._real_token else "❌",
            "sandbox_account_id": self._account_id[:10] + "..." if self._account_id else "❌",
            "real_account_id": self._real_account_id[:10] + "..." if self._real_account_id else "❌",
            "is_real_account": self._is_real_account,
            "current_token": self.get_current_token()[:10] + "..." if self.get_current_token() else "❌",
            "current_account_id": self.account_id[:10] + "..." if self.account_id else "❌",
        }

    def __str__(self) -> str:
        """Строковое представление."""
        info = self.get_info()
        return (
            f"AppContext:\n"
            f"  Режим: {'Реальный' if info['is_real_account'] else 'Песочница'}\n"
            f"  Токен: {info['current_token']}\n"
            f"  Account ID: {info['current_account_id']}"
        )


# Глобальный экземпляр (singleton)
_app_context: AppContext | None = None


def get_app_context() -> AppContext:
    """Получить глобальный экземпляр контекста."""
    global _app_context
    if _app_context is None:
        _app_context = AppContext()
    return _app_context


def init_app_context(sandbox_token: str = "", real_token: str = "") -> AppContext:
    """Инициализировать контекст с токенами."""
    global _app_context
    _app_context = AppContext()
    _app_context.sandbox_token = sandbox_token
    _app_context.real_token = real_token
    return _app_context
