# core/account_api.py
"""
API для работы с реальным счётом T-Investments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from t_tech.invest import Client


def quotation_to_float(q) -> float:
    """Конвертирует Quotation в float."""
    if q is None:
        return 0.0
    if isinstance(q, (int, float)):
        return float(q)
    # Это объект Quotation с полями units и nano
    units = int(getattr(q, "units", 0) or 0)
    nano = int(getattr(q, "nano", 0) or 0)
    return units + nano / 1e9


def money_to_float(m) -> float:
    """Конвертирует MoneyValue в float."""
    if m is None:
        return 0.0
    if isinstance(m, (int, float)):
        return float(m)
    units = int(getattr(m, "units", 0) or 0)
    nano = int(getattr(m, "nano", 0) or 0)
    return units + nano / 1e9


@dataclass
class AccountInfo:
    """Информация о счёте."""
    account_id: str
    account_type: str  # "TinkoffInvest" или др.
    status: str  # "Opened", "Closed" и т.д.
    currency: str  # "RUB"


@dataclass
class PortfolioPosition:
    """Позиция в портфеле."""
    figi: str
    instrument_type: str
    quantity: float
    balance: float
    position_avg_price: float
    current_price: Optional[float] = None
    ticker: Optional[str] = None
    name: Optional[str] = None


@dataclass
class PortfolioResult:
    """Результат запроса портфеля."""
    total_amount_bonds: float
    total_amount_currencies: float
    total_amount_etf: float
    total_amount_futures: float
    total_amount_shares: float
    total_amount_portfolio: float
    positions: list[PortfolioPosition]


def get_accounts(token: str) -> list[AccountInfo]:
    """
    Получить список счетов пользователя.
    """
    print(f"[get_accounts] Начинаем запрос счетов...")
    accounts = []
    try:
        with Client(token=token) as client:
            print(f"[get_accounts] Клиент создан")
            resp = client.users.get_accounts()
            print(f"[get_accounts] Ответ получен: {resp}")
            for acc in getattr(resp, "accounts", []) or []:
                print(f"[get_accounts] Счёт: id={getattr(acc, 'id', '')}, status={getattr(acc, 'status', '')}")
                accounts.append(AccountInfo(
                    account_id=getattr(acc, "id", ""),
                    account_type=getattr(acc, "type", ""),
                    status=getattr(acc, "status", ""),
                    currency=getattr(acc, "currency", "RUB"),
                ))
    except Exception as e:
        print(f"[get_accounts] Ошибка: {e}")
        import traceback
        traceback.print_exc()
    print(f"[get_accounts] Возвращаем {len(accounts)} счетов")
    return accounts


def get_portfolio(token: str, account_id: str) -> PortfolioResult:
    """
    Получить портфель реального счёта.
    """
    print(f"[get_portfolio] Запрашиваем портфель для счёта: {account_id}")
    try:
        with Client(token=token) as client:
            print(f"[get_portfolio] Клиент создан")
            resp = client.operations.get_portfolio(account_id=account_id)
            print(f"[get_portfolio] Ответ получен")

        positions = []
        for pos in getattr(resp, "positions", []) or []:
            figi = getattr(pos, "figi", "")
            print(f"[get_portfolio] Обработка позиции: {figi}")
            figi = getattr(pos, "figi", "")

            # Получаем текущую цену
            current_price = None
            ticker = None
            name = None
            try:
                lp_resp = client.market_data.get_last_prices(figi=[figi])
                for lp in getattr(lp_resp, "last_prices", []) or []:
                    p = getattr(lp, "price", None)
                    if p:
                        units = int(getattr(p, "units", 0) or 0)
                        nano = int(getattr(p, "nano", 0) or 0)
                        current_price = units + nano / 1e9
            except Exception:
                pass

            # Получаем информацию об инструменте
            try:
                ins_resp = client.instruments.find_instrument(id=figi)
                for inst in getattr(ins_resp, "instruments", []) or []:
                    ticker = getattr(inst, "ticker", None)
                    name = getattr(inst, "name", None)
                    break
            except Exception:
                pass

            # Средняя цена покупки
            avg_price = quotation_to_float(getattr(pos, "average_position_price", None))

            # Конвертируем quantity (количество бумаг)
            quantity = quotation_to_float(getattr(pos, "quantity", 0))

            # В T-Invest API у позиций нет поля balance, используем quantity
            # balance = quotation_to_float(getattr(pos, "balance", 0))
            balance = quantity  # Для акций/облигаций balance = quantity

            print(f"[get_portfolio] Позиция {ticker or figi}: quantity={quantity}, balance={balance}")

            positions.append(PortfolioPosition(
                figi=figi,
                instrument_type=getattr(pos, "instrument_type", ""),
                quantity=quantity,
                balance=balance,
                position_avg_price=avg_price,
                current_price=current_price,
                ticker=ticker,
                name=name,
            ))

        print(f"[get_portfolio] Всего позиций: {len(positions)}")

        result = PortfolioResult(
            total_amount_bonds=money_to_float(getattr(resp, "total_amount_bonds", None)),
            total_amount_currencies=money_to_float(getattr(resp, "total_amount_currencies", None)),
            total_amount_etf=money_to_float(getattr(resp, "total_amount_etf", None)),
            total_amount_futures=money_to_float(getattr(resp, "total_amount_futures", None)),
            total_amount_shares=money_to_float(getattr(resp, "total_amount_shares", None)),
            total_amount_portfolio=money_to_float(getattr(resp, "total_amount_portfolio", None)),
            positions=positions,
        )
        print(f"[get_portfolio] Портфель возвращён: {result.total_amount_portfolio}")
        return result

    except Exception as e:
        print(f"[get_portfolio] Ошибка: {e}")
        import traceback
        traceback.print_exc()
        raise


# ============================================================================
# Функции для обратной совместимости со старым кодом
# ============================================================================

def fetch_sandbox_accounts(token: str) -> list[dict]:
    """
    Получить список счетов песочницы (для совместимости).
    Возвращает список словарей с информацией о счетах.
    """
    accounts = []
    with Client(token=token) as client:
        try:
            sb = getattr(client, "sandbox", None)
            if sb is None:
                return accounts

            resp = sb.get_sandbox_accounts()
            for acc in getattr(resp, "accounts", []) or []:
                accounts.append({
                    "account_id": getattr(acc, "id", ""),
                    "account_type": getattr(acc, "type", ""),
                    "status": getattr(acc, "status", ""),
                    "currency": getattr(acc, "currency", "RUB"),
                })
        except Exception:
            pass
    return accounts


def fetch_money_balance(token: str, account_id: str) -> dict:
    """
    Получить денежный баланс счёта песочницы (для совместимости).
    Возвращает словарь с балансами по валютам.
    """
    result = {"RUB": 0.0, "USD": 0.0, "EUR": 0.0}

    with Client(token=token) as client:
        try:
            sb = getattr(client, "sandbox", None)
            if sb is None:
                return result

            resp = sb.get_sandbox_portfolio(account_id=account_id)
            for pos in getattr(resp, "positions", []) or []:
                if getattr(pos, "instrument_type", "") == "currency":
                    currency = getattr(pos, "figi", "")
                    # Преобразуем FIGI валюты в код
                    if "RUB" in currency:
                        curr_code = "RUB"
                    elif "USD" in currency:
                        curr_code = "USD"
                    elif "EUR" in currency:
                        curr_code = "EUR"
                    else:
                        curr_code = currency[:3]

                    balance = float(getattr(pos, "balance", 0) or 0)
                    result[curr_code] = result.get(curr_code, 0.0) + balance
        except Exception:
            pass

    return result

