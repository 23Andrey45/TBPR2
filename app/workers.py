# app/workers.py
"""
Фоновые задачи (workers) для PyQt приложения.
"""
from __future__ import annotations

import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

from PyQt6 import QtCore
from t_tech.invest import Client, CandleInterval

from core.trading_logic import CandleData, quotation_to_float
from core.dividends_api import fetch_dividends, DividendEvent
from core.orders_api import get_orders, load_orders_from_cache


class CandleLoader(QtCore.QObject):
    candle_received = QtCore.pyqtSignal(object)  # CandleData
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, instrument_id: str, from_: datetime, interval: CandleInterval):
        super().__init__()
        self.token = token
        self.instrument_id = instrument_id
        self.from_ = from_
        self.interval = interval
        self._stopping = False

    @QtCore.pyqtSlot()
    def stop(self):
        self._stopping = True

    @QtCore.pyqtSlot()
    def run(self):
        try:
            with Client(self.token) as client:
                for candle in client.get_all_candles(
                        instrument_id=self.instrument_id,
                        from_=self.from_,
                        interval=self.interval,
                ):
                    if self._stopping:
                        break
                    self.candle_received.emit(
                        CandleData(
                            time=candle.time,
                            open=quotation_to_float(candle.open),
                            high=quotation_to_float(candle.high),
                            low=quotation_to_float(candle.low),
                            close=quotation_to_float(candle.close),
                            volume=int(candle.volume),
                        )
                    )
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class DividendsLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # list[DividendEvent]
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
            divs = fetch_dividends(self.token, figi=self.figi, from_=self.from_, to=self.to)
            self.loaded.emit(divs)
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
            from core.instruments_catalog import fetch_available_shares, fetch_available_bonds, fetch_available_etfs

            payload = {
                "share": fetch_available_shares(self.token),
                "bond": fetch_available_bonds(self.token),
                "etf": fetch_available_etfs(self.token),
            }
            self.loaded.emit(payload)
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class TradingStatusLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, figis: list[str]):
        super().__init__()
        self.token = token
        self.figi = figis

    @QtCore.pyqtSlot()
    def run(self):
        try:
            # Заглушка для загрузки статусов торгов
            self.loaded.emit({})
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()


# ============================================================================
# SandboxHistoryLoader - загрузчик истории для песочницы
# ============================================================================

class SandboxHistoryLoader(QtCore.QObject):
    """Загрузчик истории сделок из песочницы."""
    loaded = QtCore.pyqtSignal(object)  # dict с fills и orders
    progress = QtCore.pyqtSignal(int)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, days: int = 30):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.days = days

    @QtCore.pyqtSlot()
    def run(self):
        """Загрузить историю сделок и ордеров из песочницы."""
        try:
            from t_tech.invest import Client

            print(f"[SandboxHistoryLoader] Загрузка истории за {self.days} дней...")
            self.progress.emit(10)

            now = datetime.now(timezone.utc)

            fills = []
            orders = []

            with Client(self.token) as client:
                sb = getattr(client, "sandbox", None)
                if sb is None:
                    raise RuntimeError("Sandbox API not available")

                # Загружаем сделки (fills)
                self.progress.emit(30)
                print("[SandboxHistoryLoader] Загрузка сделок...")
                try:
                    fills_resp = sb.get_sandbox_fills(account_id=self.account_id)
                    for fill in getattr(fills_resp, "fills", []) or []:
                        fill_dict = {
                            "deal_id": getattr(fill, "deal_id", ""),
                            "account_id": self.account_id,
                            "figi": getattr(fill, "figi", ""),
                            "ticker": "",
                            "side": getattr(fill, "side", ""),
                            "lots": float(getattr(fill, "quantity", 0) or 0),
                            "price": str(getattr(fill, "price", None)),
                            "status": "done",
                            "order_id": getattr(fill, "order_id", ""),
                            "source": "sandbox",
                            "time": getattr(fill, "time", now.isoformat()),
                        }
                        fills.append(fill_dict)
                    print(f"[SandboxHistoryLoader] Загружено {len(fills)} сделок")
                except Exception as e:
                    print(f"[SandboxHistoryLoader] Ошибка загрузки сделок: {e}")

                self.progress.emit(60)

                # Загружаем ордера
                print("[SandboxHistoryLoader] Загрузка ордеров...")
                try:
                    orders_resp = sb.get_sandbox_orders(account_id=self.account_id)
                    for order in getattr(orders_resp, "orders", []) or []:
                        order_dict = {
                            "local_id": getattr(order, "order_id", ""),
                            "account_id": self.account_id,
                            "figi": getattr(order, "figi", ""),
                            "ticker": "",
                            "side": getattr(order, "direction", ""),
                            "order_type": str(getattr(order, "order_type", "")),
                            "lots_requested": int(getattr(order, "lots_requested", 0) or 0),
                            "lots_executed": int(getattr(order, "lots_executed", 0) or 0),
                            "price": str(getattr(order, "price", None)),
                            "order_id": getattr(order, "order_id", ""),
                            "server_status": str(getattr(order, "status", "")),
                            "status_ui": self._map_status(getattr(order, "status", "")),
                            "message": "",
                            "created_at": getattr(order, "created", now.isoformat()),
                            "updated_at": getattr(order, "updated", None),
                        }
                        orders.append(order_dict)
                    print(f"[SandboxHistoryLoader] Загружено {len(orders)} ордеров")
                except Exception as e:
                    print(f"[SandboxHistoryLoader] Ошибка загрузки ордеров: {e}")

            self.progress.emit(100)

            result = {"fills": fills, "orders": orders}
            self.loaded.emit(result)

        except Exception as e:
            import traceback
            print(f"[SandboxHistoryLoader] Ошибка: {e}")
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()

    def _map_status(self, status: str) -> str:
        """Маппинг статусов ордера."""
        status_map = {
            "ORDER_STATUS_NEW": "Новый",
            "ORDER_STATUS_PARTIALLY": "Частично",
            "ORDER_STATUS_FILLED": "Исполнена",
            "ORDER_STATUS_CANCELLED": "Отменена",
            "ORDER_STATUS_REJECTED": "Отклонена",
            "ORDER_STATUS_REPLACED": "Заменён",
            "ORDER_STATUS_CANCELING": "Отменяется",
            "ORDER_STATUS_NEW_DONE": "Новый исполнен",
            "ORDER_STATUS_NEW_REJECT": "Новый отклонён",
        }
        return status_map.get(status, status)


# ============================================================================
# OrdersLoader - загрузчик активных заявок для реального счёта
# ============================================================================

class OrdersLoader(QtCore.QObject):
    """Загрузчик активных заявок в фоновом потоке."""
    loaded = QtCore.pyqtSignal(object)  # list[Order]
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

            # Загружаем с сервера (только активные, кэш не используем)
            print(f"[OrdersLoader] Запрашиваем активные заявки...")
            orders = get_orders(self.token, self.account_id)
            print(f"[OrdersLoader] Получено активных заявок: {len(orders)}")

            self.loaded.emit(orders)
        except Exception as e:
            import traceback
            print(f"[OrdersLoader] Ошибка: {e}")
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()
