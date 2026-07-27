# real_account/plan_models.py
"""
Модели данных для таблицы "План" заявок.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional, Any
from enum import Enum


class PlanOrderStatus(str, Enum):
    """Статусы заявки в плане."""
    PENDING = "pending"  # Ожидает выставления
    SUBMITTED = "submitted"  # Выставлена на сервер
    FILLED = "filled"  # Исполнена
    CANCELLED = "cancelled"  # Отменена (на сервере или вручную)
    REJECTED = "rejected"  # Отклонена сервером


@dataclass
class PlanOrder:
    """
    Заявка в плане.

    Атрибуты:
        id: Уникальный ID записи в плане (генерируется локально)
        figi: FIGI инструмента
        ticker: Тикер инструмента
        quantity: Количество лотов
        price: Цена заявки
        direction: Направление ("buy" или "sell")
        order_type: Тип заявки ("limit" или "market")
        status: Статус заявки в плане
        server_order_id: ID заявки на сервере (если выставлена)
        created_at: Время создания записи в плане
        updated_at: Время последнего обновления
        last_submit_at: Время последней отправки на сервер
        note: Примечание пользователя
    """
    id: str = ""
    figi: str = ""
    ticker: str = ""
    quantity: float = 0.0
    price: float = 0.0
    direction: str = "buy"
    order_type: str = "limit"
    status: str = PlanOrderStatus.PENDING.value
    server_order_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    last_submit_at: Optional[str] = None
    note: str = ""

    @staticmethod
    def generate_id() -> str:
        """Сгенерировать уникальный ID для записи плана."""
        import uuid
        return f"plan_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def now_iso() -> str:
        """Получить текущее время в ISO формате."""
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def create(
            cls,
            figi: str,
            ticker: str,
            quantity: float,
            price: float,
            direction: str,
            order_type: str = "limit",
            note: str = "",
    ) -> "PlanOrder":
        """Создать новую запись плана."""
        now = cls.now_iso()
        return cls(
            id=cls.generate_id(),
            figi=figi,
            ticker=ticker,
            quantity=quantity,
            price=price,
            direction=direction.lower(),
            order_type=order_type.lower(),
            status=PlanOrderStatus.PENDING.value,
            created_at=now,
            updated_at=now,
            note=note,
        )

    def mark_submitted(self, server_order_id: str) -> None:
        """Отметить как выставленную на сервер."""
        self.status = PlanOrderStatus.SUBMITTED.value
        self.server_order_id = server_order_id
        self.last_submit_at = self.now_iso()
        self.updated_at = self.now_iso()

    def mark_filled(self) -> None:
        """Отметить как исполненную."""
        self.status = PlanOrderStatus.FILLED.value
        self.updated_at = self.now_iso()

    def mark_cancelled(self) -> None:
        """Отметить как отмененную."""
        self.status = PlanOrderStatus.CANCELLED.value
        self.updated_at = self.now_iso()

    def mark_rejected(self) -> None:
        """Отметить как отклоненную."""
        self.status = PlanOrderStatus.REJECTED.value
        self.updated_at = self.now_iso()

    def reset_to_pending(self) -> None:
        """Сбросить в состояние ожидания (для повторного выставления)."""
        self.status = PlanOrderStatus.PENDING.value
        self.server_order_id = None
        self.last_submit_at = None
        self.updated_at = self.now_iso()

    def can_submit(self) -> bool:
        """Можно ли выставить заявку на сервер."""
        return self.status in (
            PlanOrderStatus.PENDING.value,
            PlanOrderStatus.CANCELLED.value,
            PlanOrderStatus.REJECTED.value,
        )

    def to_dict(self) -> dict[str, Any]:
        """Преобразовать в словарь."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanOrder":
        """Создать из словаря."""
        return cls(
            id=data.get("id", ""),
            figi=data.get("figi", ""),
            ticker=data.get("ticker", ""),
            quantity=float(data.get("quantity", 0) or 0),
            price=float(data.get("price", 0) or 0),
            direction=data.get("direction", "buy"),
            order_type=data.get("order_type", "limit"),
            status=data.get("status", PlanOrderStatus.PENDING.value),
            server_order_id=data.get("server_order_id"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            last_submit_at=data.get("last_submit_at"),
            note=data.get("note", ""),
        )
