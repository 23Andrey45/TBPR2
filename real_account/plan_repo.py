# real_account/plan_repo.py
"""
Репозиторий для сохранения и загрузки плана заявок.
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from app.config import DATA_DIR
from real_account.plan_models import PlanOrder

# Путь к файлу хранения плана
PLAN_FILE = DATA_DIR / "real_account_plan.json"


def get_plan_file_path() -> Path:
    """Получить путь к файлу плана."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return PLAN_FILE


def save_plan(orders: list[PlanOrder]) -> Path:
    """
    Сохранить план заявок на диск.

    Args:
        orders: Список заявок плана

    Returns:
        Путь к сохранённому файлу
    """
    path = get_plan_file_path()

    data = {
        "version": "1.0",
        "updated": datetime.now(timezone.utc).isoformat(),
        "orders": [order.to_dict() for order in orders],
    }

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[PlanRepo] Сохранено {len(orders)} заявок плана в {path}")
    return path


def load_plan() -> list[PlanOrder]:
    """
    Загрузить план заявок с диска.

    Returns:
        Список заявок плана
    """
    path = get_plan_file_path()

    if not path.exists():
        print(f"[PlanRepo] Файл плана не найден: {path}")
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        orders = [PlanOrder.from_dict(d) for d in data.get("orders", [])]
        print(f"[PlanRepo] Загружено {len(orders)} заявок плана из {path}")
        return orders
    except Exception as e:
        print(f"[PlanRepo] Ошибка загрузки плана: {e}")
        return []


def add_to_plan(order: PlanOrder) -> list[PlanOrder]:
    """
    Добавить заявку в план.

    Args:
        order: Заявка для добавления

    Returns:
        Обновлённый список плана
    """
    orders = load_plan()
    orders.insert(0, order)  # Добавляем в начало
    save_plan(orders)
    return orders


def update_plan_order(order: PlanOrder) -> list[PlanOrder]:
    """
    Обновить заявку в плане.

    Args:
        order: Заявка с обновлёнными данными

    Returns:
        Обновлённый список плана
    """
    orders = load_plan()

    for i, existing in enumerate(orders):
        if existing.id == order.id:
            orders[i] = order
            break

    save_plan(orders)
    return orders


def get_plan_order_by_id(order_id: str) -> Optional[PlanOrder]:
    """
    Получить заявку из плана по ID.

    Args:
        order_id: ID заявки в плане

    Returns:
        Заявка или None
    """
    orders = load_plan()

    for order in orders:
        if order.id == order_id:
            return order

    return None


def get_plan_order_by_server_id(server_order_id: str) -> Optional[PlanOrder]:
    """
    Получить заявку из плана по ID заявки на сервере.

    Args:
        server_order_id: ID заявки на сервере

    Returns:
        Заявка или None
    """
    orders = load_plan()

    for order in orders:
        if order.server_order_id == server_order_id:
            return order

    return None


def get_pending_orders() -> list[PlanOrder]:
    """
    Получить заявки, ожидающие выставления.

    Returns:
        Список заявок со статусом PENDING или CANCELLED
    """
    orders = load_plan()
    return [o for o in orders if o.can_submit()]


def delete_plan_order(order_id: str) -> list[PlanOrder]:
    """
    Удалить заявку из плана.

    Args:
        order_id: ID заявки в плане

    Returns:
        Обновлённый список плана
    """
    orders = load_plan()
    orders = [o for o in orders if o.id != order_id]
    save_plan(orders)
    return orders


def clear_filled_orders() -> int:
    """
    Очистить исполненные заявки из плана.

    Returns:
        Количество удалённых заявок
    """
    from real_account.plan_models import PlanOrderStatus

    orders = load_plan()
    initial_count = len(orders)

    orders = [
        o for o in orders
        if o.status != PlanOrderStatus.FILLED.value
    ]

    save_plan(orders)
    return initial_count - len(orders)
