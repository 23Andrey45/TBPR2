from __future__ import annotations

from datetime import datetime, timezone
import inspect
from typing import Any

from PyQt6 import QtCore
from t_tech.invest import Client


class CancelSandboxOrderWorker(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, order_id: str):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.order_id = order_id

    @QtCore.pyqtSlot()
    def run(self):
        try:
            with Client(token=self.token) as client:
                sb = getattr(client, "sandbox", None)
                if sb is not None and hasattr(sb, "cancel_sandbox_order"):
                    method = sb.cancel_sandbox_order
                    try:
                        method(account_id=self.account_id, order_id=self.order_id)
                    except TypeError:
                        req = make_request_for_method(method)
                        set_req_attr(req, ["account_id", "accountId", "id"], self.account_id)
                        set_req_attr(req, ["order_id", "orderId"], self.order_id)
                        method(request=req)
        except Exception:
            pass
        finally:
            self.loaded.emit({"ok": True})
            self.finished.emit()


class RecentDealsLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, from_dt: datetime):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.from_dt = from_dt

    @QtCore.pyqtSlot()
    def run(self):
        try:
            rows = self._load()
            self.loaded.emit({"rows": rows, "error": ""})
        except Exception as exc:
            msg = str(exc)
            err = "UNAUTHENTICATED" if "UNAUTHENTICATED" in msg.upper() else "ERROR"
            self.loaded.emit({"rows": [], "error": err})
        finally:
            self.finished.emit()

    def _load(self) -> list[dict[str, Any]]:
        with Client(token=self.token) as client:
            method = None
            sb = getattr(client, "sandbox", None)
            if sb is not None:
                method = getattr(sb, "get_sandbox_operations", None)

            if method is None:
                ops = getattr(client, "operations", None)
                if ops is not None:
                    method = getattr(ops, "get_operations", None)

            if method is None:
                return []

            resp = None
            try:
                resp = method(account_id=self.account_id, from_=self.from_dt, to=datetime.now(timezone.utc))
            except TypeError:
                req = make_request_for_method(method)
                set_req_attr(req, ["account_id", "accountId", "id"], self.account_id)
                set_req_attr(req, ["from_", "from"], self.from_dt)
                set_req_attr(req, ["to"], datetime.now(timezone.utc))
                resp = method(request=req)

            items = list(getattr(resp, "operations", []) or [])
            out: list[dict[str, Any]] = []
            for op in items:
                op_type = str(getattr(op, "operation_type", "") or getattr(op, "type", ""))
                up = op_type.upper()
                if "BUY" not in up and "SELL" not in up:
                    continue

                dt = getattr(op, "date", None) or datetime.now(timezone.utc)
                figi = str(getattr(op, "figi", "") or "")
                side = "BUY" if "BUY" in up else "SELL"
                qty = getattr(op, "quantity", None)
                lots = int(float(qty)) if qty is not None else 0

                p = getattr(op, "price", None) or getattr(op, "payment", None)
                price = money_like_to_str(p)

                out.append(
                    {
                        "deal_id": str(getattr(op, "id", "") or ""),
                        "account_id": self.account_id,
                        "time": dt.isoformat() if hasattr(dt, "isoformat") else str(dt),
                        "figi": figi,
                        "ticker": figi,
                        "side": side,
                        "order_type": "MARKET",
                        "lots": lots,
                        "price": price,
                        "status": "Исполнена",
                        "order_id": str(getattr(op, "parent_operation_id", "") or ""),
                        "source": "server",
                    }
                )

            return out


class OrderStatesLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, order_ids: list[str]):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.order_ids = order_ids

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.loaded.emit({"states": self._load_states(), "error": ""})
        except Exception as exc:
            msg = str(exc)
            err = "UNAUTHENTICATED" if "UNAUTHENTICATED" in msg.upper() else "ERROR"
            self.loaded.emit({"states": {}, "error": err})
        finally:
            self.finished.emit()

    def _load_states(self) -> dict[str, str]:
        out: dict[str, str] = {}
        with Client(token=self.token) as client:
            sb = getattr(client, "sandbox", None)
            if sb is None:
                return out

            method = getattr(sb, "get_sandbox_order_state", None)
            if method is None:
                method = getattr(sb, "get_sandbox_order", None)
            if method is None:
                return out

            for oid in self.order_ids:
                try:
                    try:
                        resp = method(account_id=self.account_id, order_id=oid)
                    except TypeError:
                        req = make_request_for_method(method)
                        set_req_attr(req, ["account_id", "accountId", "id"], self.account_id)
                        set_req_attr(req, ["order_id", "orderId"], oid)
                        resp = method(request=req)

                    out[oid] = str(getattr(resp, "execution_report_status", "") or getattr(resp, "status", "") or "")
                except Exception:
                    out[oid] = ""

        return out


def make_request_for_method(method):
    sig = inspect.signature(method)
    if "request" not in sig.parameters:
        return None
    default_req = sig.parameters["request"].default
    req_cls = type(default_req)
    try:
        return req_cls()
    except Exception:
        return default_req


def set_req_attr(obj: object, names: list[str], value: Any) -> bool:
    if obj is None:
        return False
    for name in names:
        if hasattr(obj, name):
            try:
                setattr(obj, name, value)
                return True
            except Exception:
                pass
    return False


def money_like_to_str(x: Any) -> str:
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