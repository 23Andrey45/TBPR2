# core/account_api.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from t_tech.invest import Client


def fetch_sandbox_accounts(token: str) -> list[AccountInfo]:
    token = token.strip()
    with Client(token=token) as client:
        resp = client.sandbox.get_sandbox_accounts()
        accounts = getattr(resp, "accounts", []) or []

        out: list[AccountInfo] = []
        for a in accounts:
            account_id = getattr(a, "id", "") or getattr(a, "account_id", "")
            out.append(AccountInfo(
                account_id=str(account_id),
                name="SANDBOX",
                type="SANDBOX",
                status="",
            ))
        return out

def money_to_float(m) -> float:
    return float(getattr(m, "units", 0)) + float(getattr(m, "nano", 0)) / 1e9


@dataclass(frozen=True)
class AccountInfo:
    account_id: str
    name: str
    type: str
    status: str


@dataclass(frozen=True)
class MoneyRow:
    currency: str
    available: float
    blocked: float


def _get_by_paths(root, paths: Iterable[tuple[str, ...]]):
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


def _users_service(client):
    # чаще всего так: client.users
    svc = _get_by_paths(client, [
        ("users",),
        ("users_service",),
        ("services", "users"),
        ("services", "users_service"),
    ])
    if svc is None:
        raise AttributeError("Не найден users service у client (нет client.users)")
    return svc


def _operations_service(client):
    svc = _get_by_paths(client, [
        ("operations",),
        ("operations_service",),
        ("services", "operations"),
        ("services", "operations_service"),
    ])
    if svc is None:
        raise AttributeError("Не найден operations service у client (нет client.operations)")
    return svc


def fetch_accounts(token: str) -> list[AccountInfo]:
    """
    Возвращает аккаунты (account_id нужен для запросов баланса/портфеля).
    """
    with Client(token) as client:
        users = _users_service(client)
        resp = users.get_accounts()
        accounts = getattr(resp, "accounts", []) or []

        out: list[AccountInfo] = []
        for a in accounts:
            out.append(AccountInfo(
                account_id=str(getattr(a, "id", "")),
                name=str(getattr(a, "name", "")),
                type=str(getattr(a, "type", "")),
                status=str(getattr(a, "status", "")),
            ))
        return out


def fetch_money_balance(token: str, account_id: str) -> list[MoneyRow]:
    """
    Денежные позиции по валютам из get_positions():
    - money: доступные
    - blocked_money: заблокированные
    """
    with Client(token) as client:
        ops = _operations_service(client)
        resp = ops.get_positions(account_id=account_id)

        money = getattr(resp, "money", []) or []
        blocked = getattr(resp, "blocked_money", []) or []

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
            MoneyRow(
                currency=cur,
                available=available_map.get(cur, 0.0),
                blocked=blocked_map.get(cur, 0.0),
            )
            for cur in currencies
        ]
