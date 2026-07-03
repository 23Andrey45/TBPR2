# core/sandbox_trading_api.py
from __future__ import annotations

from dataclasses import dataclass
import inspect
import uuid
from typing import Any, Optional

from t_tech.invest.grpc import Client

try:
    from t_tech.invest.grpc.orders_pb2 import OrderDirection, OrderType  # type: ignore
except Exception:
    OrderDirection = None  # type: ignore
    OrderType = None  # type: ignore


@dataclass(frozen=True)
class TradingStatusInfo:
    figi: str
    instrument_uid: str
    ticker: str
    class_code: str
    trading_status: str
    api_trade_available: bool
    market_order_available: bool
    limit_order_available: bool


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    status: str


@dataclass(frozen=True)
class OrderAttemptResult:
    sent: bool
    message: str
    trading: TradingStatusInfo
    order: Optional[OrderResult]


@dataclass(frozen=True)
class PortfolioRow:
    figi: str
    uid: str
    instrument_id: str
    lots: float
    quantity: float
    avg_price: float
    avg_price_currency: str
    current_price: float
    current_price_currency: str
    expected_yield: float


def _to_float(x: Any) -> float:
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    if hasattr(x, "units") and hasattr(x, "nano"):
        return float(getattr(x, "units", 0)) + float(getattr(x, "nano", 0)) / 1e9
    if hasattr(x, "value"):
        try:
            return float(x.value)
        except Exception:
            return 0.0
    return 0.0


def _get_by_paths(root: object, paths: list[tuple[str, ...]]):
    for path in paths:
        obj = root
        ok = True
        for p in path:
            if not hasattr(obj, p):
                ok = False
                break
            obj = getattr(obj, p)
        if ok:
            return obj
    return None


def _sandbox_service(client: Client):
    svc = _get_by_paths(
        client,
        [
            ("sandbox",),
            ("sandbox_service",),
            ("services", "sandbox"),
            ("services", "sandbox_service"),
        ],
    )
    if svc is None:
        raise AttributeError("Не найден sandbox service у Client (нет client.sandbox)")
    return svc


def _make_request_from_signature(method) -> Optional[object]:
    sig = inspect.signature(method)
    if "request" not in sig.parameters:
        return None
    default_req = sig.parameters["request"].default
    req_cls = type(default_req)
    try:
        return req_cls()
    except Exception:
        return default_req


def _set_attr_if_exists(obj: object, names: list[str], value: Any) -> bool:
    for name in names:
        if hasattr(obj, name):
            try:
                setattr(obj, name, value)
                return True
            except Exception:
                pass
    return False


def get_trading_status(token: str, *, figi: str = "", instrument_id: str = "") -> TradingStatusInfo:
    token = token.strip()
    with Client(token=token) as client:
        md = getattr(client, "market_data", None)
        if md is None or not hasattr(md, "get_trading_status"):
            raise AttributeError("У клиента нет market_data.get_trading_status")

        method = md.get_trading_status
        req = _make_request_from_signature(method)
        if req is None:
            raise TypeError(f"get_trading_status без request-параметра: {inspect.signature(method)}")

        if figi:
            _set_attr_if_exists(req, ["figi"], figi)
        if instrument_id:
            _set_attr_if_exists(req, ["instrument_id", "instrumentId"], instrument_id)

        resp = method(request=req)

        return TradingStatusInfo(
            figi=str(getattr(resp, "figi", "") or ""),
            instrument_uid=str(getattr(resp, "instrument_uid", "") or ""),
            ticker=str(getattr(resp, "ticker", "") or ""),
            class_code=str(getattr(resp, "class_code", "") or ""),
            trading_status=str(getattr(resp, "trading_status", "") or ""),
            api_trade_available=bool(getattr(resp, "api_trade_available_flag", False)),
            market_order_available=bool(getattr(resp, "market_order_available_flag", False)),
            limit_order_available=bool(getattr(resp, "limit_order_available_flag", False)),
        )


def _set_instrument_fields(req: object, *, figi: str, uid: str, instrument_id: str) -> None:
    # figi -> только figi
    if hasattr(req, "figi"):
        if not figi:
            raise ValueError("Request ожидает поле figi, но figi пустой")
        req.figi = figi  # type: ignore[attr-defined]

    # uid
    if hasattr(req, "instrument_uid") and uid:
        req.instrument_uid = uid  # type: ignore[attr-defined]
    elif hasattr(req, "uid") and uid:
        req.uid = uid  # type: ignore[attr-defined]

    # instrument_id
    if hasattr(req, "instrument_id") and instrument_id:
        req.instrument_id = instrument_id  # type: ignore[attr-defined]


def post_sandbox_market_order(
    token: str,
    account_id: str,
    *,
    instrument_id: str,
    figi: str = "",
    uid: str = "",
    direction: str,
    lots: int = 1,
) -> OrderResult:
    token = token.strip()
    account_id = (account_id or "").strip()
    if not account_id:
        raise ValueError("post_sandbox_market_order: пустой account_id")

    if OrderDirection is None or OrderType is None:
        raise ImportError("Не удалось импортировать OrderDirection/OrderType из t_tech.invest.grpc.orders_pb2")

    dir_enum = OrderDirection.ORDER_DIRECTION_BUY if direction.upper() == "BUY" else OrderDirection.ORDER_DIRECTION_SELL
    type_enum = OrderType.ORDER_TYPE_MARKET

    with Client(token=token) as client:
        sb = _sandbox_service(client)
        method = getattr(sb, "post_sandbox_order", None)
        if method is None:
            raise AttributeError("В sandbox service нет post_sandbox_order")

        req = _make_request_from_signature(method)
        if req is None:
            raise TypeError(f"post_sandbox_order без request-параметра: {inspect.signature(method)}")

        _set_attr_if_exists(req, ["account_id", "accountId", "id"], account_id)
        _set_instrument_fields(req, figi=figi, uid=uid, instrument_id=instrument_id)

        if not _set_attr_if_exists(req, ["quantity", "lots"], int(lots)):
            raise AttributeError("В request не найдено поле quantity/lots")

        _set_attr_if_exists(req, ["direction"], dir_enum)
        _set_attr_if_exists(req, ["order_type", "orderType", "type"], type_enum)
        _set_attr_if_exists(req, ["order_id", "orderId"], str(uuid.uuid4()))

        resp = method(request=req)

        order_id = str(getattr(resp, "order_id", "") or getattr(resp, "orderId", "") or "")
        status = str(getattr(resp, "execution_report_status", "") or getattr(resp, "status", "") or "")
        return OrderResult(order_id=order_id, status=status)


def try_post_sandbox_market_order(
    token: str,
    account_id: str,
    *,
    instrument_id: str,
    figi: str = "",
    uid: str = "",
    direction: str,
    lots: int = 1,
) -> OrderAttemptResult:
    trading = get_trading_status(token, figi=figi, instrument_id=instrument_id)

    if not trading.market_order_available:
        msg = (
            f"Торги сейчас недоступны для MARKET: {trading.ticker} {trading.class_code} | "
            f"status={trading.trading_status} | market={trading.market_order_available} | limit={trading.limit_order_available}"
        )
        return OrderAttemptResult(sent=False, message=msg, trading=trading, order=None)

    order = post_sandbox_market_order(
        token,
        account_id,
        instrument_id=instrument_id,
        figi=figi,
        uid=uid,
        direction=direction,
        lots=lots,
    )
    return OrderAttemptResult(sent=True, message="Заявка отправлена", trading=trading, order=order)


def get_sandbox_portfolio(token: str, account_id: str) -> list[PortfolioRow]:
    token = token.strip()
    account_id = (account_id or "").strip()
    if not account_id:
        raise ValueError("get_sandbox_portfolio: пустой account_id")

    with Client(token=token) as client:
        sb = _sandbox_service(client)
        method = getattr(sb, "get_sandbox_portfolio", None)
        if method is None:
            raise AttributeError("В sandbox service нет get_sandbox_portfolio")

        req = _make_request_from_signature(method)
        if req is None:
            resp = method(account_id)
        else:
            _set_attr_if_exists(req, ["account_id", "accountId", "id"], account_id)
            resp = method(request=req)

        positions = list(getattr(resp, "positions", []) or [])

        out: list[PortfolioRow] = []
        for p in positions:
            figi_ = str(getattr(p, "figi", "") or "")
            uid_ = str(getattr(p, "instrument_uid", "") or getattr(p, "uid", "") or "")
            instrument_id_ = str(getattr(p, "instrument_id", "") or "")

            qty = _to_float(getattr(p, "quantity", None))
            lots = _to_float(getattr(p, "quantity_lots", None))

            avg_price_obj = getattr(p, "average_position_price", None)
            avg_price = _to_float(avg_price_obj)
            avg_cur = str(getattr(avg_price_obj, "currency", "") or "")

            cur_price_obj = getattr(p, "current_price", None)
            cur_price = _to_float(cur_price_obj)
            cur_cur = str(getattr(cur_price_obj, "currency", "") or "")

            exp_yield = _to_float(getattr(p, "expected_yield", None))

            out.append(
                PortfolioRow(
                    figi=figi_,
                    uid=uid_,
                    instrument_id=instrument_id_,
                    lots=lots,
                    quantity=qty,
                    avg_price=avg_price,
                    avg_price_currency=avg_cur,
                    current_price=cur_price,
                    current_price_currency=cur_cur,
                    expected_yield=exp_yield,
                )
            )

        return out
