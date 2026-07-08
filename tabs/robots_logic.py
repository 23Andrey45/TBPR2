from __future__ import annotations

import inspect
from decimal import Decimal
from typing import Any

from PyQt6 import QtCore
from t_tech.invest import Client

from core.sandbox_orders_api import (
    get_sandbox_order_state,
    list_active_sandbox_orders,
    try_post_sandbox_limit_order,
)


def _price_key(price: float) -> str:
    return f"{float(price):.6f}"


def _decimals_from_tick(tick: float) -> int:
    try:
        d = Decimal(str(float(tick))).normalize()
    except Exception:
        return 2
    exp = d.as_tuple().exponent
    if exp >= 0:
        return 0
    return min(8, max(0, -exp))


def _fmt_price(value: float, tick: float) -> str:
    decimals = _decimals_from_tick(tick)
    return f"{float(value):.{decimals}f}"


def _is_active_status(status: str) -> bool:
    s = str(status or "").upper()
    return ("NEW" in s) or ("PARTIALLY" in s) or ("ACTIVE" in s) or (s in ("4", "5", "6"))


def _make_request_for_method(method):
    sig = inspect.signature(method)
    if "request" not in sig.parameters:
        return None
    default_req = sig.parameters["request"].default
    req_cls = type(default_req)
    try:
        return req_cls()
    except Exception:
        return default_req


def _set_req_attr(obj: object, names: list[str], value: Any) -> bool:
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


class _RobotsSyncWorker(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # list[dict]
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, robots: list[dict]):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.robots = robots

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.loaded.emit(self._sync())
        except Exception:
            self.loaded.emit(self.robots)
        finally:
            self.finished.emit()

    def _sync(self) -> list[dict]:
        active_server = list_active_sandbox_orders(self.token, self.account_id)
        active_by_id = {o.order_id: o for o in active_server if o.order_id}

        for rec in self.robots:
            if str(rec.get("status", "")) != "Запущен":
                continue

            levels = [float(x) for x in (rec.get("grid_levels", []) or [])]
            if not levels:
                continue

            deals_by_level = rec.get("deals_by_level", {}) or {}
            active_orders = rec.get("active_orders", []) or []

            next_active: list[dict] = []
            for ao in active_orders:
                oid = str(ao.get("order_id", "") or "")
                if not oid:
                    continue

                srv = active_by_id.get(oid)
                if srv is not None:
                    ao["status"] = str(srv.status)
                    ao["lots_executed"] = int(srv.lots_executed)
                    if _is_active_status(str(srv.status)):
                        next_active.append(ao)
                    elif "FILL" in str(srv.status).upper() or str(srv.status) == "1":
                        self._count_fill(rec, ao, deals_by_level)
                    continue

                state = get_sandbox_order_state(self.token, self.account_id, oid)
                if state is None:
                    continue

                ao["status"] = state.status
                ao["lots_executed"] = int(state.lots_executed)
                if _is_active_status(state.status):
                    next_active.append(ao)
                elif "FILL" in str(state.status).upper() or str(state.status) == "1":
                    self._count_fill(rec, ao, deals_by_level)

            rec["active_orders"] = next_active
            rec["deals_by_level"] = deals_by_level

            last_trade = float(rec.get("last_trade_price", 0.0) or 0.0)
            buy_level = max([x for x in levels if x < last_trade], default=None)
            sell_level = min([x for x in levels if x > last_trade], default=None)

            buy_orders = [x for x in next_active if str(x.get("side", "")).upper() == "BUY"]
            sell_orders = [x for x in next_active if str(x.get("side", "")).upper() == "SELL"]

            self._ensure_side_order(rec, next_active, buy_orders, "BUY", buy_level)
            self._ensure_side_order(rec, next_active, sell_orders, "SELL", sell_level)

            rec["active_orders"] = next_active

        return self.robots

    def _ensure_side_order(
        self,
        rec: dict,
        next_active: list[dict],
        side_orders: list[dict],
        side: str,
        desired_level: float | None,
    ):
        if desired_level is None:
            for ao in side_orders:
                self._cancel_order(ao)
                if ao in next_active:
                    next_active.remove(ao)
            return

        desired_key = _price_key(desired_level)
        keep: dict | None = None
        for ao in side_orders:
            level_key = _price_key(float(ao.get("level_price", 0.0) or 0.0))
            if keep is None and level_key == desired_key:
                keep = ao
                continue
            self._cancel_order(ao)
            if ao in next_active:
                next_active.remove(ao)

        if keep is None:
            self._place_order(rec, next_active, side, desired_level)

    def _place_order(self, rec: dict, active_orders: list[dict], side: str, level_price: float):
        figi = str(rec.get("instrument_figi", "") or "")
        if not figi:
            return

        result = try_post_sandbox_limit_order(
            self.token,
            self.account_id,
            figi=figi,
            direction=side,
            lots=1,
            price_str=f"{float(level_price):.6f}",
        )
        if not result.sent:
            return

        active_orders.append(
            {
                "order_id": result.order_id,
                "side": side,
                "level_price": float(level_price),
                "price": float(level_price),
                "status": "ACTIVE",
                "lots_requested": 1,
                "lots_executed": 0,
            }
        )

    def _cancel_order(self, ao: dict):
        oid = str(ao.get("order_id", "") or "")
        if not oid:
            return
        try:
            with Client(token=self.token) as client:
                sb = getattr(client, "sandbox", None)
                if sb is None:
                    return
                method = getattr(sb, "cancel_sandbox_order", None)
                if method is None:
                    return
                try:
                    method(account_id=self.account_id, order_id=oid)
                except TypeError:
                    req = _make_request_for_method(method)
                    _set_req_attr(req, ["account_id", "accountId", "id"], self.account_id)
                    _set_req_attr(req, ["order_id", "orderId"], oid)
                    method(request=req)
        except Exception:
            pass

    def _count_fill(self, rec: dict, active_order: dict, deals_by_level: dict):
        level_price = float(active_order.get("level_price", 0.0) or 0.0)
        key = _price_key(level_price)
        row = deals_by_level.get(key, {"b": 0, "s": 0})
        side = str(active_order.get("side", "")).upper()
        if side == "BUY":
            row["b"] = int(row.get("b", 0) or 0) + 1
        elif side == "SELL":
            row["s"] = int(row.get("s", 0) or 0) + 1
        deals_by_level[key] = row
        rec["last_trade_price"] = level_price
