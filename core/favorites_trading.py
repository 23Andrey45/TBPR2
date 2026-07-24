# core/favorites_trading.py
"""
Получение информации о состоянии торговли избранными инструментами.
Модуль не зависит от UI и может использоваться в любом месте.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone

from t_tech.invest import Client
from core.favorites_repo import load_favorites
from app.config import FAVORITES_FILE


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


@dataclass
class TradingInstrumentInfo:
    """Информация об инструменте для торговли."""
    figi: str
    ticker: str
    name: str
    kind: str  # share, bond, etf

    # Позиция
    quantity: float = 0.0
    balance: float = 0.0
    average_price: float = 0.0

    # Котировка
    current_price: Optional[float] = None
    last_price_time: Optional[datetime] = None

    # P&L
    market_value: float = 0.0  # рыночная стоимость
    total_cost: float = 0.0  # средняя стоимость
    unrealized_pnl: float = 0.0  # нереализованный P&L
    unrealized_pnl_percent: float = 0.0  # P&L в процентах

    # Статус торгов
    trading_status: str = ""  # "open", "closed", "break"

    def to_dict(self) -> dict:
        """Преобразовать в словарь."""
        return {
            "figi": self.figi,
            "ticker": self.ticker,
            "name": self.name,
            "kind": self.kind,
            "quantity": self.quantity,
            "balance": self.balance,
            "average_price": self.average_price,
            "current_price": self.current_price,
            "last_price_time": self.last_price_time.isoformat() if self.last_price_time else None,
            "market_value": self.market_value,
            "total_cost": self.total_cost,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_percent": self.unrealized_pnl_percent,
            "trading_status": self.trading_status,
        }


def get_favorites_trading_info(token: str, account_id: str) -> list[TradingInstrumentInfo]:
    """
    Получить полную информацию о торговле избранными инструментами.

    Args:
        token: Токен T-Investments
        account_id: ID счёта

    Returns:
        Список информации по каждому избранному инструменту
    """
    # Загружаем избранное
    favorites = load_favorites(FAVORITES_FILE)
    if not favorites:
        return []

    # Собираем FIGI для запроса котировок
    figi_list = [info.figi for info in favorites.values() if info.figi]

    # Получаем позиции по счёту
    positions_by_figi = {}
    try:
        with Client(token=token) as client:
            # Песочница
            sb = getattr(client, "sandbox", None)
            if sb:
                try:
                    portfolio = sb.get_sandbox_portfolio(account_id=account_id)
                    for pos in getattr(portfolio, "positions", []) or []:
                        figi = getattr(pos, "figi", "")
                        if figi:
                            positions_by_figi[figi] = pos
                except Exception:
                    pass

            # Если песочница не доступна, пробуем реальный счёт
            if not positions_by_figi:
                try:
                    portfolio = client.operations.get_portfolio(account_id=account_id)
                    for pos in getattr(portfolio, "positions", []) or []:
                        figi = getattr(pos, "figi", "")
                        if figi:
                            positions_by_figi[figi] = pos
                except Exception:
                    pass
    except Exception as e:
        print(f"[get_favorites_trading_info] Error getting positions: {e}")

    # Получаем котировки
    quotes_by_figi = {}
    if figi_list:
        try:
            with Client(token=token) as client:
                resp = client.market_data.get_last_prices(figi=figi_list)
                for lp in getattr(resp, "last_prices", []) or []:
                    figi = getattr(lp, "figi", "")
                    if figi:
                        quotes_by_figi[figi] = lp
        except Exception as e:
            print(f"[get_favorites_trading_info] Error getting quotes: {e}")

    # Получаем статусы торгов из котировок
    trading_status_by_figi = {}
    if figi_list:
        try:
            with Client(token=token) as client:
                # Получаем котировки - там есть информация о статусе
                resp = client.market_data.get_last_prices(figi=figi_list)
                for lp in getattr(resp, "last_prices", []) or []:
                    figi = getattr(lp, "figi", "")
                    if figi:
                        # Пытаемся получить статус из котировки
                        status_obj = getattr(lp, "market_status", None)
                        if status_obj:
                            status_name = getattr(status_obj, "name", "unknown")
                            trading_status_by_figi[figi] = status_name
                        else:
                            # Если статуса нет, считаем что торги идут (есть цена)
                            trading_status_by_figi[figi] = "MARKET_STATUS_OPEN"
        except Exception as e:
            print(f"[get_favorites_trading_info] Error getting trading status from quotes: {e}")

    # Собираем информацию по каждому инструменту
    result = []

    for info in favorites.values():
        if not info.figi:
            continue

        trading_info = TradingInstrumentInfo(
            figi=info.figi,
            ticker=info.ticker,
            name=info.name,
            kind=info.kind,
        )

        # Позиция
        pos = positions_by_figi.get(info.figi)
        if pos:
            quantity = quotation_to_float(getattr(pos, "quantity", 0))
            balance = quotation_to_float(getattr(pos, "balance", 0))

            # Средняя цена
            avg_price_obj = getattr(pos, "average_position_price", None)
            average_price = quotation_to_float(avg_price_obj)

            trading_info.quantity = quantity
            trading_info.balance = balance
            trading_info.average_price = average_price
            trading_info.total_cost = quantity * average_price

        # Котировка
        quote = quotes_by_figi.get(info.figi)
        if quote:
            price_obj = getattr(quote, "price", None)
            if price_obj:
                current_price = float(getattr(price_obj, "units", 0) or 0) + \
                                float(getattr(price_obj, "nano", 0) or 0) / 1e9
                trading_info.current_price = current_price
                trading_info.market_value = trading_info.quantity * current_price

            time_obj = getattr(quote, "time", None)
            if time_obj:
                trading_info.last_price_time = time_obj

        # P&L
        if trading_info.current_price and trading_info.average_price and trading_info.quantity > 0:
            trading_info.unrealized_pnl = trading_info.market_value - trading_info.total_cost
            if trading_info.total_cost > 0:
                trading_info.unrealized_pnl_percent = (trading_info.unrealized_pnl / trading_info.total_cost) * 100

        # Статус торгов
        trading_info.trading_status = trading_status_by_figi.get(info.figi, "unknown")

        result.append(trading_info)

    # Сортируем по ticker
    result.sort(key=lambda x: x.ticker)

    return result


def get_favorites_summary(token: str, account_id: str) -> dict:
    """
    Получить сводную информацию по избранным инструментам.

    Returns:
        Словарь с общей статистикой
    """
    instruments = get_favorites_trading_info(token, account_id)

    total_market_value = sum(inst.market_value for inst in instruments)
    total_cost = sum(inst.total_cost for inst in instruments)
    total_pnl = sum(inst.unrealized_pnl for inst in instruments)

    total_pnl_percent = 0.0
    if total_cost > 0:
        total_pnl_percent = (total_pnl / total_cost) * 100

    # Инструменты в плюсе/минусе
    profitable = [inst for inst in instruments if inst.unrealized_pnl > 0]
    unprofitable = [inst for inst in instruments if inst.unrealized_pnl < 0]
    flat = [inst for inst in instruments if inst.unrealized_pnl == 0]

    return {
        "total_instruments": len(instruments),
        "total_market_value": total_market_value,
        "total_cost": total_cost,
        "total_unrealized_pnl": total_pnl,
        "total_unrealized_pnl_percent": total_pnl_percent,
        "profitable_count": len(profitable),
        "unprofitable_count": len(unprofitable),
        "flat_count": len(flat),
        "instruments": [inst.to_dict() for inst in instruments],
    }
