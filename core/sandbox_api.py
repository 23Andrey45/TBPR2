# core/sandbox_api.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Any, Optional
import inspect

from t_tech.invest.grpc import Client

# ВАЖНО: в твоей версии ответы печатаются как MoneyValue(currency='rub', ...)
# это НЕ protobuf-объект из common_pb2, а модель из t_tech.invest.grpc.common
try:
    from t_tech.invest.grpc.common import MoneyValue  # type: ignore
except Exception:  # fallback (если вдруг в другой версии common отсутствует)
    from t_tech.invest.grpc.common_pb2 import MoneyValue  # type: ignore


def money_to_float(m) -> float:
    return float(getattr(m, "units", 0)) + float(getattr(m, "nano", 0)) / 1e9


@dataclass(frozen=True)
class SandboxAccountInfo:
    account_id: str
    type: str
    name: str
    status: str
    opened_date: str


@dataclass(frozen=True)
class MoneyRow:
    currency: str
    available: float
    blocked: float


def _get_by_paths(root: object, paths: Iterable[tuple[str, ...]]):
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


def _set_field(obj: object, names: list[str], value: Any) -> bool:
    """
    Для твоей версии request-объекты "обёрточные", поэтому чаще всего работает
    простое setattr (CopyFrom может отсутствовать).
    """
    for name in names:
        if hasattr(obj, name):
            try:
                setattr(obj, name, value)
                return True
            except Exception:
                pass
    return False


def list_sandbox_accounts(token: str) -> list[SandboxAccountInfo]:
    token = token.strip()
    with Client(token=token) as client:
        sb = _sandbox_service(client)
        resp = sb.get_sandbox_accounts()
        accounts = list(getattr(resp, "accounts", []) or [])

        out: list[SandboxAccountInfo] = []
        for a in accounts:
            out.append(
                SandboxAccountInfo(
                    account_id=str(getattr(a, "id", "")),
                    type=str(getattr(a, "type", "")),
                    name=str(getattr(a, "name", "")),
                    status=str(getattr(a, "status", "")),
                    opened_date=str(getattr(a, "opened_date", "")),
                )
            )
        return out


def open_sandbox_account(token: str) -> str:
    token = token.strip()
    with Client(token=token) as client:
        sb = _sandbox_service(client)
        resp = sb.open_sandbox_account()
        account_id = getattr(resp, "account_id", "") or ""
        if not account_id:
            raise RuntimeError(f"open_sandbox_account(): пустой account_id, resp={resp!r}")
        return str(account_id)


def sandbox_pay_in(token: str, account_id: str, currency: str, units: int, nano: int = 0) -> None:
    """
    Пополнение sandbox.
    В твоей версии сигнатура вида: sandbox_pay_in(request=SandboxPayInRequest(...))
    """
    token = token.strip()
    account_id = (account_id or "").strip()
    if not account_id:
        raise ValueError("sandbox_pay_in: пустой account_id")

    # оставляем нижний регистр (rub/usd/eur), как в ответах API
    currency = (currency or "").strip().lower()
    if not currency:
        raise ValueError("sandbox_pay_in: пустая currency")

    with Client(token=token) as client:
        sb = _sandbox_service(client)

        req = _make_request_from_signature(sb.sandbox_pay_in)
        if req is None:
            raise TypeError(f"sandbox_pay_in: не вижу параметр request в сигнатуре {inspect.signature(sb.sandbox_pay_in)}")

        ok_acc = _set_attr_if_exists(req, ["account_id", "accountId", "id"], account_id)
        if not ok_acc:
            raise AttributeError("sandbox_pay_in: не удалось установить account_id в request")

        amount = MoneyValue(currency=currency, units=int(units), nano=int(nano))
        ok_amt = _set_field(req, ["amount", "money"], amount)
        if not ok_amt:
            raise AttributeError("sandbox_pay_in: не удалось установить amount/money в request")

        sb.sandbox_pay_in(request=req)


def get_money_balance(token: str, account_id: str) -> list[MoneyRow]:
    """
    Деньги для sandbox правильнее брать через:
      client.sandbox.get_sandbox_withdraw_limits(...)
    В твоей версии метод есть (ты показал список).
    """
    token = token.strip()
    account_id = (account_id or "").strip()
    if not account_id:
        raise ValueError("get_money_balance: пустой account_id")

    with Client(token=token) as client:
        sb = _sandbox_service(client)

        if not hasattr(sb, "get_sandbox_withdraw_limits"):
            raise AttributeError("В sandbox service нет get_sandbox_withdraw_limits (ожидалось, что он есть).")

        method = sb.get_sandbox_withdraw_limits
        req = _make_request_from_signature(method)
        if req is None:
            # fallback: позиционный
            resp = method(account_id)
        else:
            _set_attr_if_exists(req, ["account_id", "accountId", "id"], account_id)
            resp = method(request=req)

        # у тебя в ответе поля называются money=[] и blocked=[]
        money = list(getattr(resp, "money", []) or [])
        blocked = list(getattr(resp, "blocked", []) or [])

        available_map: dict[str, float] = {}
        blocked_map: dict[str, float] = {}

        for m in money:
            cur = str(getattr(m, "currency", "UNKNOWN"))
            available_map[cur] = available_map.get(cur, 0.0) + money_to_float(m)

        for m in blocked:
            cur = str(getattr(m, "currency", "UNKNOWN"))
            blocked_map[cur] = blocked_map.get(cur, 0.0) + money_to_float(m)

        currencies = sorted(set(available_map.keys()) | set(blocked_map.keys()))
        return [
            MoneyRow(currency=cur, available=available_map.get(cur, 0.0), blocked=blocked_map.get(cur, 0.0))
            for cur in currencies
        ]
