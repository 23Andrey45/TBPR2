# core/sandbox_orders_api.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import inspect
import uuid
from typing import Any, Optional

from t_tech.invest.grpc import Client

from core.sandbox_trading_api import get_trading_status  # уже есть у тебя

try:
    from t_tech.invest.grpc.orders_pb2 import OrderDirection, OrderType  # type: ignore
except Exception:
    OrderDirection = None  # type: ignore
    OrderType = None  # type: ignore

# Quotation (цена) — обычно именно так передаётся limit price
try:
    from t_tech.invest.grpc.common import Quotation  # type: ignore
except Exception:
    from t_tech.invest.grpc.common_pb2 import Quotation  # type: ignore


@dataclass(frozen=True)
class ActiveOrder:
    order_id: str
    figi: str
    direction: str
    order_type: str
    lots_requested: int
    lots_executed: int
    price: str
    status: str


@dataclass(frozen=True)
class PlaceOrderAttempt:
    sent: bool
    message: str
    order_id: str


@dataclass(frozen=True)
class OrderState:
    order_id: str
    status: str
    lots_requested: int
    lots_executed: int


def _sandbox_service(client: Client):
    sb = getattr(client, "sandbox", None)
    if sb is None:
        raise AttributeError("У Client нет sandbox")
    return sb


def _make_request(method) -> object:
    sig = inspect.signature(method)
    if "request" not in sig.parameters:
        raise TypeError(f"Метод без request-параметра: {sig}")
    default_req = sig.parameters["request"].default
    req_cls = type(default_req)
    try:
        return req_cls()
    except Exception:
        return default_req


def _set(obj: object, names: list[str], value: Any) -> bool:
    for n in names:
        if hasattr(obj, n):
            setattr(obj, n, value)
            return True
    return False


def _parse_price_to_quotation(price_str: str) -> Quotation:
    """
    Принимаем строку, делаем Decimal, режем до 9 знаков вниз (наноточки),
    и собираем Quotation(units, nano) без float.
    """
    s = (price_str or "").strip().replace(",", ".")
    if not s:
        raise ValueError("Цена пустая")

    d = Decimal(s)
    if d <= 0:
        raise ValueError("Цена должна быть > 0")

    d = d.quantize(Decimal("0.000000001"), rounding=ROUND_DOWN)

    units = int(d)  # целая часть
    nano = int((d - Decimal(units)) * Decimal(1_000_000_000))
    return Quotation(units=units, nano=nano)


def try_post_sandbox_limit_order(
    token: str,
    account_id: str,
    *,
    figi: str,
    direction: str,     # "BUY" / "SELL"
    lots: int,
    price_str: str,
) -> PlaceOrderAttempt:
    """
    Вариант B: если limit недоступен — НЕ отправляем, возвращаем понятное сообщение.
    """
    token = token.strip()
    account_id = (account_id or "").strip()
    figi = (figi or "").strip()

    if not account_id:
        return PlaceOrderAttempt(False, "Нет account_id", "")
    if not figi:
        return PlaceOrderAttempt(False, "Нет FIGI у выбранной акции (торговать нельзя)", "")
    if lots <= 0:
        return PlaceOrderAttempt(False, "Lots должно быть > 0", "")

    ts = get_trading_status(token, figi=figi, instrument_id=figi)
    if not ts.limit_order_available:
        return PlaceOrderAttempt(
            False,
            f"LIMIT недоступен сейчас: {ts.ticker} {ts.class_code} status={ts.trading_status} limit={ts.limit_order_available}",
            "",
        )

    if OrderDirection is None or OrderType is None:
        return PlaceOrderAttempt(False, "Не импортировались OrderDirection/OrderType", "")

    price = _parse_price_to_quotation(price_str)
    dir_enum = OrderDirection.ORDER_DIRECTION_BUY if direction.upper() == "BUY" else OrderDirection.ORDER_DIRECTION_SELL
    type_enum = OrderType.ORDER_TYPE_LIMIT

    with Client(token=token) as client:
        sb = _sandbox_service(client)
        method = sb.post_sandbox_order
        req = _make_request(method)

        _set(req, ["account_id", "accountId", "id"], account_id)
        # в t_tech sandbox order обычно figi
        if not _set(req, ["figi"], figi):
            # fallback на instrument_id, если вдруг так
            _set(req, ["instrument_id", "instrumentId"], figi)

        _set(req, ["direction"], dir_enum)
        _set(req, ["order_type", "orderType", "type"], type_enum)
        _set(req, ["quantity", "lots"], int(lots))
        _set(req, ["order_id", "orderId"], str(uuid.uuid4()))

        # price
        if not _set(req, ["price"], price):
            return PlaceOrderAttempt(False, "В request нет поля price (не могу поставить LIMIT)", "")

        resp = method(request=req)
        order_id = str(getattr(resp, "order_id", "") or getattr(resp, "orderId", "") or "")
        return PlaceOrderAttempt(True, "Заявка отправлена", order_id)


def list_active_sandbox_orders(token: str, account_id: str) -> list[ActiveOrder]:
    token = token.strip()
    account_id = (account_id or "").strip()
    if not account_id:
        return []

    with Client(token=token) as client:
        sb = _sandbox_service(client)
        method = sb.get_sandbox_orders
        req = _make_request(method)
        _set(req, ["account_id", "accountId", "id"], account_id)

        resp = method(request=req)
        orders = list(getattr(resp, "orders", []) or [])

        out: list[ActiveOrder] = []
        for o in orders:
            order_id = str(getattr(o, "order_id", "") or getattr(o, "orderId", "") or "")
            figi = str(getattr(o, "figi", "") or "")

            direction = str(getattr(o, "direction", "") or "")
            order_type = str(getattr(o, "order_type", "") or getattr(o, "type", "") or "")

            lots_req = int(getattr(o, "lots_requested", 0) or getattr(o, "quantity", 0) or 0)
            lots_exec = int(getattr(o, "lots_executed", 0) or 0)

            status = str(getattr(o, "execution_report_status", "") or getattr(o, "status", "") or "")

            # цена может лежать в разных полях
            p = getattr(o, "price", None) or getattr(o, "initial_security_price", None) or getattr(o, "initial_order_price", None)
            if p is None:
                price_s = ""
            else:
                if hasattr(p, "units") and hasattr(p, "nano"):
                    price_s = f"{p.units}.{abs(int(p.nano)):09d}".rstrip("0").rstrip(".")
                else:
                    price_s = str(p)

            out.append(ActiveOrder(
                order_id=order_id,
                figi=figi,
                direction=direction,
                order_type=order_type,
                lots_requested=lots_req,
                lots_executed=lots_exec,
                price=price_s,
                status=status,
            ))
        return out


def get_sandbox_order_state(token: str, account_id: str, order_id: str) -> OrderState | None:
    token = token.strip()
    account_id = (account_id or "").strip()
    order_id = (order_id or "").strip()
    if not account_id or not order_id:
        return None

    with Client(token=token) as client:
        sb = _sandbox_service(client)
        method = getattr(sb, "get_sandbox_order_state", None)
        if method is None:
            method = getattr(sb, "get_sandbox_order", None)
        if method is None:
            return None

        try:
            resp = method(account_id=account_id, order_id=order_id)
        except TypeError:
            req = _make_request(method)
            _set(req, ["account_id", "accountId", "id"], account_id)
            _set(req, ["order_id", "orderId"], order_id)
            resp = method(request=req)

        lots_req = int(getattr(resp, "lots_requested", 0) or getattr(resp, "quantity", 0) or 0)
        lots_exec = int(getattr(resp, "lots_executed", 0) or 0)
        status = str(getattr(resp, "execution_report_status", "") or getattr(resp, "status", "") or "")
        oid = str(getattr(resp, "order_id", "") or getattr(resp, "orderId", "") or order_id)
        return OrderState(order_id=oid, status=status, lots_requested=lots_req, lots_executed=lots_exec)