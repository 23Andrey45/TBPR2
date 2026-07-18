# workers/history_loader_workers.py
"""
Воркеры для загрузки истории сделок с сервера T-Invest API.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from PyQt6 import QtCore
from t_tech.invest import Client


class SandboxHistoryLoader(QtCore.QObject):
    """
    Воркер для загрузки истории сделок из sandbox.

    Signals:
        loaded: dict - {"fills": [...], "orders": [...], "count": int}
        progress: int - процент выполнения (0-100)
        error: str - ошибка
        finished: void - завершение
    """
    loaded = QtCore.pyqtSignal(object)
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
        print(f"[SandboxHistoryLoader] START: {self.days} days, account={self.account_id}")
        try:
            fills = []
            orders = []

            # Загрузка операций (сделок)
            self.progress.emit(10)
            print(f"[SandboxHistoryLoader] Loading operations...")
            fills = self._load_operations()
            print(f"[SandboxHistoryLoader] Loaded {len(fills)} operations")

            self.progress.emit(50)

            # Загрузка активных ордеров
            self.progress.emit(60)
            print(f"[SandboxHistoryLoader] Loading active orders...")
            orders = self._load_active_orders()
            print(f"[SandboxHistoryLoader] Loaded {len(orders)} orders")

            self.progress.emit(100)

            result = {
                "fills": fills,
                "orders": orders,
                "count": len(fills) + len(orders),
            }

            print(f"[SandboxHistoryLoader] DONE: {result['count']} records")
            self.loaded.emit(result)

        except Exception as e:
            import traceback
            print(f"[SandboxHistoryLoader] ERROR: {e}")
            traceback.print_exc()
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()

    def _load_operations(self) -> list[dict[str, Any]]:
        """Загрузить операции (сделки) с сервера."""
        out = []

        print(f"[SandboxHistoryLoader] _load_operations START: account={self.account_id}, days={self.days}")

        with Client(token=self.token) as client:
            # Пытаемся получить sandbox operations
            sb = getattr(client, "sandbox", None)
            method = None

            print(f"[SandboxHistoryLoader] sandbox service exists: {sb is not None}")

            if sb:
                method = getattr(sb, "get_sandbox_operations", None)
                print(f"[SandboxHistoryLoader] get_sandbox_operations exists: {method is not None}")

            if not method:
                # Fallback к operations service
                ops = getattr(client, "operations", None)
                print(f"[SandboxHistoryLoader] operations service exists: {ops is not None}")
                if ops:
                    method = getattr(ops, "get_operations", None)
                    print(f"[SandboxHistoryLoader] get_operations exists: {method is not None}")

            if not method:
                print("[SandboxHistoryLoader] No operations method found - using fallback")
                return []

            # Загружаем по периодам (по 30 дней)
            to_dt = datetime.now(timezone.utc)
            from_dt = to_dt - timedelta(days=self.days)

            print(f"[SandboxHistoryLoader] Loading from {from_dt} to {to_dt}")

            try:
                print(f"[SandboxHistoryLoader] Calling method(account_id={self.account_id})")
                resp = method(account_id=self.account_id, from_=from_dt, to=to_dt)
                items = list(getattr(resp, "operations", []) or [])

                print(f"[SandboxHistoryLoader] API returned {len(items)} total operations")

                # Логируем первые 5 операций для отладки
                for i, op in enumerate(items[:5]):
                    op_type = str(getattr(op, "operation_type", "") or getattr(op, "type", ""))
                    figi = str(getattr(op, "figi", "") or "")
                    qty = getattr(op, "quantity", None)
                    print(f"[SandboxHistoryLoader]   [{i}] type={op_type}, figi={figi}, qty={qty}")

                buy_sell_count = 0
                for op in items:
                    # Получаем тип операции (может быть числом или строкой)
                    op_type_raw = getattr(op, "operation_type", None) or getattr(op, "type", None)

                    # Преобразуем числовые коды в строки
                    # 1=Buy, 2=Sell, 15=Buy, 16=Sell, 19=Buy (margin), 20=Sell (margin)
                    if isinstance(op_type_raw, int):
                        op_type_map = {
                            1: "BUY",
                            2: "SELL",
                            15: "BUY",
                            16: "SELL",
                            19: "BUY",
                            20: "SELL",
                        }
                        op_type = op_type_map.get(op_type_raw, str(op_type_raw))
                    else:
                        op_type = str(op_type_raw or "")

                    up = op_type.upper()

                    # Только сделки BUY/SELL
                    if "BUY" not in up and "SELL" not in up:
                        # Пропускаем дивиденды, комиссии и т.д.
                        continue

                    buy_sell_count += 1
                    dt = getattr(op, "date", None) or datetime.now(timezone.utc)
                    figi = str(getattr(op, "figi", "") or "")
                    side = "BUY" if op_type in ("BUY", "1", "15", "19") else "SELL"
                    qty = getattr(op, "quantity", None)
                    lots = int(float(qty)) if qty is not None else 0

                    p = getattr(op, "price", None) or getattr(op, "payment", None)
                    price = self._money_to_str(p)

                    out.append({
                        "deal_id": str(getattr(op, "id", "") or ""),
                        "account_id": self.account_id,
                        "time": dt.isoformat() if hasattr(dt, "isoformat") else str(dt),
                        "figi": figi,
                        "ticker": figi,  # TODO: заменить на тикер
                        "side": side,
                        "order_type": "MARKET",
                        "lots": lots,
                        "price": price,
                        "status": "Исполнена",
                        "order_id": str(getattr(op, "parent_operation_id", "") or ""),
                        "source": "server",
                    })

                print(f"[SandboxHistoryLoader] Filtered to {buy_sell_count} BUY/SELL operations, out={len(out)}")

            except Exception as e:
                print(f"[SandboxHistoryLoader] Error loading operations: {e}")
                import traceback
                traceback.print_exc()

        return out

    def _load_active_orders(self) -> list[dict[str, Any]]:
        """Загрузить активные ордера с сервера."""
        out = []

        try:
            from core.sandbox_orders_api import list_active_sandbox_orders
            orders = list_active_sandbox_orders(self.token, self.account_id)

            for o in orders:
                out.append({
                    "local_id": f"server_{o.order_id}",
                    "account_id": self.account_id,
                    "figi": o.figi,
                    "ticker": o.figi,  # TODO: заменить на тикер
                    "side": o.direction,
                    "order_type": o.order_type,
                    "lots_requested": o.lots_requested,
                    "lots_executed": o.lots_executed,
                    "price": o.price,
                    "order_id": o.order_id,
                    "server_status": o.status,
                    "status_ui": self._ui_status(o.status, o.lots_requested, o.lots_executed),
                    "message": "",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
        except Exception as e:
            print(f"[SandboxHistoryLoader] Error loading orders: {e}")

        return out

    def _money_to_str(self, x: Any) -> str:
        """Преобразовать денежное значение в строку."""
        if x is None:
            return ""
        if hasattr(x, "units") and hasattr(x, "nano"):
            units = int(getattr(x, "units", 0) or 0)
            nano = int(getattr(x, "nano", 0) or 0)
            val = units + nano / 1e9
            return f"{val:.6f}".rstrip("0").rstrip(".")
        try:
            return str(float(x))
        except Exception:
            return str(x)

    def _ui_status(self, server_status: str, lots_req: int = 0, lots_exec: int = 0) -> str:
        """Преобразовать статус сервера в UI статус."""
        if not server_status:
            return "Не активна"

        s = server_status.upper().replace("EXECUTION_REPORT_STATUS_", "")

        numeric_map = {
            "0": "Не активна",
            "1": "Исполнена",
            "2": "Отклонена",
            "3": "Отменена",
            "4": "Активна",
            "5": "Частично исполнена",
            "6": "Активна",
        }

        if s in numeric_map:
            return numeric_map[s]

        if "PARTIALLY" in s:
            return "Частично исполнена"
        if "FILL" in s:
            return "Исполнена"
        if "CANCEL" in s:
            return "Отменена"
        if "REJECT" in s:
            return "Отклонена"
        if "NEW" in s or "ACTIVE" in s:
            return "Активна"

        return server_status
