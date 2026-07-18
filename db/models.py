# db/models.py
"""
Модели данных для базы данных.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Any
from datetime import datetime, timezone


@dataclass
class Order:
    """Модель ордера."""
    id: Optional[int] = None
    local_id: str = ""
    account_id: str = ""
    figi: str = ""
    ticker: str = ""
    side: str = ""
    order_type: str = ""
    lots_requested: int = 0
    lots_executed: int = 0
    price: str = ""
    order_id: str = ""
    server_status: str = ""
    status_ui: str = ""
    message: str = ""
    created_at: str = ""
    updated_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Order':
        """Создать из словаря."""
        return cls(
            id=data.get("id"),
            local_id=data.get("local_id", ""),
            account_id=data.get("account_id", ""),
            figi=data.get("figi", ""),
            ticker=data.get("ticker", ""),
            side=data.get("side", ""),
            order_type=data.get("order_type", ""),
            lots_requested=int(data.get("lots_requested", 0) or 0),
            lots_executed=int(data.get("lots_executed", 0) or 0),
            price=data.get("price", ""),
            order_id=data.get("order_id", ""),
            server_status=data.get("server_status", ""),
            status_ui=data.get("status_ui", ""),
            message=data.get("message", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Преобразовать в словарь."""
        return asdict(self)

    @staticmethod
    def now_iso() -> str:
        """Получить текущее время в ISO формате."""
        return datetime.now(timezone.utc).isoformat()


@dataclass
class Fill:
    """Модель исполнения (сделки)."""
    id: Optional[int] = None
    deal_id: str = ""
    account_id: str = ""
    figi: str = ""
    ticker: str = ""
    side: str = ""
    lots: int = 0
    price: str = ""
    status: str = ""
    order_id: str = ""
    source: str = ""
    time: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Fill':
        """Создать из словаря."""
        return cls(
            id=data.get("id"),
            deal_id=data.get("deal_id", ""),
            account_id=data.get("account_id", ""),
            figi=data.get("figi", ""),
            ticker=data.get("ticker", ""),
            side=data.get("side", ""),
            lots=int(data.get("lots", 0) or 0),
            price=data.get("price", ""),
            status=data.get("status", ""),
            order_id=data.get("order_id", ""),
            source=data.get("source", ""),
            time=data.get("time", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Преобразовать в словарь."""
        return asdict(self)
