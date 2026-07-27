# real_account/ra_workers.py
"""
Фоновые загрузчики для вкладки "Реальный счёт".
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from PyQt6 import QtCore

from core.account_api import get_accounts, get_portfolio
from core.operations_api import get_operations, save_operations_to_cache, load_operations_from_cache, Operation
from core.orders_api import get_orders, Order


class RealAccountLoader(QtCore.QObject):
    """Загрузчик данных счёта в фоновом потоке."""
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    @QtCore.pyqtSlot()
    def run(self):
        try:
            print(f"[RealAccountLoader] Начинаем загрузку...")
            accounts = get_accounts(self.token)
            print(f"[RealAccountLoader] Получено счетов: {len(accounts)}")

            if not accounts:
                self.error.emit("Счета не найдены. Проверьте токен.")
                self.finished.emit()
                return

            account = None
            for acc in accounts:
                if acc.status == "Opened":
                    account = acc
                    break

            if not account:
                account = accounts[0]

            print(f"[RealAccountLoader] Используем счёт: {account.account_id}")
            portfolio = get_portfolio(self.token, account.account_id)
            print(f"[RealAccountLoader] Получено позиций: {len(portfolio.positions)}")

            self.loaded.emit({
                "account": account,
                "portfolio": portfolio,
            })
        except Exception as e:
            import traceback
            print(f"[RealAccountLoader] Ошибка: {e}")
            print(traceback.format_exc())
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()


class HistoryLoader(QtCore.QObject):
    """Загрузчик истории операций в фоновом потоке."""
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, figi: str, days: int = 365):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.figi = figi
        self.days = days

    @QtCore.pyqtSlot()
    def run(self):
        try:
            print(f"[HistoryLoader] Загрузка истории для {self.figi}...")
            cached = load_operations_from_cache(self.account_id, self.figi)
            if cached:
                print(f"[HistoryLoader] Загружено из кэша: {len(cached)} операций")
                self.loaded.emit(cached)
                self.finished.emit()
                return

            to_date = datetime.now(timezone.utc)
            from_date = to_date - timedelta(days=self.days)
            print(f"[HistoryLoader] Запрашиваем историю с {from_date} по {to_date}...")
            operations = get_operations(self.token, self.account_id, from_date, to_date)

            if self.figi:
                operations = [op for op in operations if op.figi == self.figi]

            print(f"[HistoryLoader] Получено операций: {len(operations)}")

            if operations:
                save_operations_to_cache(self.account_id, self.figi, operations)
                print(f"[HistoryLoader] Сохранено в кэш")

            self.loaded.emit(operations)
        except Exception as e:
            import traceback
            print(f"[HistoryLoader] Ошибка: {e}")
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()


class OrdersLoader(QtCore.QObject):
    """Загрузчик активных заявок в фоновом потоке."""
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
            print(f"[OrdersLoader] Загрузка активных заявок...")
            orders = get_orders(self.token, self.account_id)
            print(f"[OrdersLoader] Получено активных заявок: {len(orders)}")
            self.loaded.emit(orders)
        except Exception as e:
            import traceback
            print(f"[OrdersLoader] Ошибка: {e}")
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()
