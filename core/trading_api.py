# core/trading_api.py
"""
API для торговли на реальном счёте.
Выставление заявок, отмена, получение статуса.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from t_tech.invest import Client, OrderType


@dataclass
class OrderResult:
    """Результат выставления заявки."""
    success: bool
    order_id: str = ""
    message: str = ""
    error: str = ""


def post_order(
        token: str,
        account_id: str,
        figi: str,
        quantity: int,
        price: float,
        direction: str,  # "buy" или "sell"
        order_type: str = "limit",  # "limit" или "market"
) -> OrderResult:
    """
    Выставить заявку на реальном счёте.

    Args:
        token: Токен T-Investments
        account_id: ID счёта
        figi: FIGI инструмента
        quantity: Количество лотов
        price: Цена (для limit заявок)
        direction: "buy" или "sell"
        order_type: "limit" или "market"

    Returns:
        OrderResult с результатом операции
    """
    try:
        with Client(token=token) as client:
            # Определяем направление
            if direction.lower() == "buy":
                order_direction = 1  # Buy
            else:
                order_direction = 2  # Sell

            # Определяем тип заявки
            if order_type.lower() == "market":
                order_type_enum = OrderType.ORDER_TYPE_MARKET
            else:
                order_type_enum = OrderType.ORDER_TYPE_LIMIT

            # Конвертируем цену в Quotation
            price_units = int(price)
            price_nano = int((price - price_units) * 1e9)

            # Выставляем заявку
            resp = client.orders.post_order(
                account_id=account_id,
                figi=figi,
                quantity=quantity,
                price={
                    "currency": "RUB",
                    "units": price_units,
                    "nano": price_nano,
                } if order_type.lower() == "limit" else None,
                direction=order_direction,
                order_type=order_type_enum,
            )

            order_id = getattr(resp, "order_id", "")

            return OrderResult(
                success=True,
                order_id=order_id,
                message=f"Заявка {order_id} выставлена",
            )

    except Exception as e:
        return OrderResult(
            success=False,
            error=str(e),
            message="Ошибка выставления заявки",
        )


def cancel_order(
        token: str,
        account_id: str,
        order_id: str,
) -> OrderResult:
    """
    Отменить заявку.

    Args:
        token: Токен T-Investments
        account_id: ID счёта
        order_id: ID заявки

    Returns:
        OrderResult с результатом операции
    """
    try:
        with Client(token=token) as client:
            resp = client.orders.cancel_order(
                account_id=account_id,
                order_id=order_id,
            )

            return OrderResult(
                success=True,
                message=f"Заявка {order_id} отменена",
            )

    except Exception as e:
        return OrderResult(
            success=False,
            error=str(e),
            message="Ошибка отмены заявки",
        )


def get_order_status(
        token: str,
        account_id: str,
        order_id: str,
) -> Optional[dict]:
    """
    Получить статус заявки.

    Args:
        token: Токен T-Investments
        account_id: ID счёта
        order_id: ID заявки

    Returns:
        dict со статусом заявки или None
    """
    try:
        with Client(token=token) as client:
            resp = client.orders.get_order_state(
                account_id=account_id,
                order_id=order_id,
            )

            return {
                "order_id": getattr(resp, "order_id", ""),
                "execution_status": getattr(resp, "execution_report_status", ""),
                "lots_requested": getattr(resp, "lots_requested", 0),
                "lots_executed": getattr(resp, "lots_executed", 0),
                "price": getattr(resp, "price", None),
            }

    except Exception:
        return None
