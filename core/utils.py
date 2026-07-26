# core/utils.py
"""
Общие утилиты для приложения.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def parse_datetime(value: Any) -> Optional[datetime]:
    """
    Распарсить datetime из строки (ISO формат).

    Args:
        value: Строка в ISO формате или None

    Returns:
        datetime или None
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def format_msk_time(value: Any) -> str:
    """
    Форматировать datetime в московское время.

    Args:
        value: Строка в ISO формате или datetime

    Returns:
        Строка в формате "%Y-%m-%d %H:%M:%S" (MSK)
    """
    raw = str(value or "")
    if not raw:
        return ""
    dt = parse_datetime(raw)
    if dt is None:
        return raw
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_msk = dt.astimezone(timezone.utc) + timedelta(hours=3)
    return dt_msk.strftime("%Y-%m-%d %H:%M:%S")


def ui_order_status(server_status: str, on_server: bool, lots_req: int = 0, lots_exec: int = 0) -> str:
    """
    Преобразовать статус ордера в человекочитаемый вид.

    Args:
        server_status: Статус от сервера (EXECUTION_REPORT_STATUS_...)
        on_server: Есть ли ордер на сервере
        lots_req: Запрошено лотов
        lots_exec: Исполнено лотов

    Returns:
        Человекочитаемый статус
    """
    if not on_server:
        return "Не активна"

    s = (server_status or "").upper().replace("EXECUTION_REPORT_STATUS_", "")

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

    return str(server_status) if str(server_status).strip() else "Активна"