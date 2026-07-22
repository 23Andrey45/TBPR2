# core/orders_api.py
"""
API для получения заявок (orders) с реального счёта.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
import json
from pathlib import Path

from t_tech.invest import Client
from app.config import DATA_DIR

# Маппинг статусов заявок T-Invest API
ORDER_STATUS_MAP = {
    0: "new",  # Новая
    1: "partially",  # Частично исполнена
    2: "filled",  # Исполнена
    3: "cancelled",  # Отменена
    4: "rejected",  # Отклонена
}


def get_order_status_name(status) -> str:
    """Конвертировать код статуса в строку."""
    if isinstance(status, str):
        return status
    if isinstance(status, int):
        return ORDER_STATUS_MAP.get(status, f"status_{status}")
    if hasattr(status, "name"):
        return status.name
    if hasattr(status, "value"):
        val = status.value
        if isinstance(val, int):
            return ORDER_STATUS_MAP.get(val, f"status_{val}")
        return str(val)
    return str(status)


@dataclass
class Order:
    """Заявка."""
    order_id: str
    figi: str
    instrument_uid: str
    ticker: Optional[str] = None
    name: Optional[str] = None
    order_type: str = ""  # "buy", "sell"
    status: str = ""
    lots_requested: float = 0.0
    lots_executed: float = 0.0
    price: float = 0.0
    executed_order_price: float = 0.0
    created: Optional[datetime] = None
    updated: Optional[datetime] = None


def get_orders(
        token: str,
        account_id: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
) -> list[Order]:
    """
    Получить активные заявки (без дат - только текущие).
    """
    orders = []

    with Client(token=token) as client:
        try:
            # Получаем только активные заявки (без указания дат)
            # T-Invest API возвращает только активные заявки если не указаны from/to
            resp = client.orders.get_orders(account_id=account_id)
            print(f"[get_orders] Получено активных заявок: {len(getattr(resp, 'orders', []))}")

            for order_resp in getattr(resp, "orders", []) or []:
                order_id = ""  # Инициализируем
                figi = getattr(order_resp, "figi", "")
                instrument_uid = getattr(order_resp, "instrument_uid", "")
                ticker = None
                name = None

                # Получаем информацию об инструменте
                try:
                    if instrument_uid:
                        ins_resp = client.instruments.get_instrument_by(id=instrument_uid, id_type="instrument_uid")
                        ticker = getattr(ins_resp, "ticker", None)
                        name = getattr(ins_resp, "name", None)
                    elif figi:
                        ins_resp = client.instruments.find_instrument(id=figi)
                        instruments = getattr(ins_resp, "instruments", []) or []
                        if instruments:
                            inst = instruments[0]
                            ticker = getattr(inst, "ticker", None)
                            name = getattr(inst, "name", None)
                except Exception as e:
                    print(f"[get_orders] Не удалось получить инфо об инструменте {figi}: {e}")
                    pass

                # Если не нашли ticker, используем figi
                if not ticker and figi:
                    ticker = figi

                # Получаем все поля заявки для отладки (первый раз)
                if not hasattr(get_orders, '_logged_fields'):
                    all_fields = [f for f in dir(order_resp) if not f.startswith('_')]
                    print(f"[get_orders] Поля заявки: {all_fields}")
                    # Выводим значения полей связанных с ценой
                    for field in ['price', 'order_price', 'executed_order_price', 'average_position_price']:
                        val = getattr(order_resp, field, None)
                        print(f"[get_orders]   {field} = {val} (type: {type(val).__name__})")
                    get_orders._logged_fields = True

                # Конвертируем цену заявки
                # В T-Invest API цена заявки находится в initial_order_price
                price = 0.0
                order_price = getattr(order_resp, "initial_order_price", None)

                if order_price:
                    # Обработка Quotation объекта
                    if hasattr(order_price, "units") and hasattr(order_price, "nano"):
                        price = float(getattr(order_price, "units", 0) or 0) + float(
                            getattr(order_price, "nano", 0) or 0) / 1e9
                    elif isinstance(order_price, (int, float)):
                        price = float(order_price)

                # Конвертируем исполненную цену
                executed_price = 0.0
                exec_price = getattr(order_resp, "executed_order_price", None)
                if exec_price:
                    # Обработка Quotation объекта
                    if hasattr(exec_price, "units") and hasattr(exec_price, "nano"):
                        executed_price = float(getattr(exec_price, "units", 0) or 0) + float(
                            getattr(exec_price, "nano", 0) or 0) / 1e9
                    elif isinstance(exec_price, (int, float)):
                        executed_price = float(exec_price)

                # Получаем ID заявки (если ещё не получен)
                if not order_id:
                    order_id = getattr(order_resp, "order_id", "")

                print(
                    f"[get_orders] Заявка {order_id[:8]}...: price_raw={order_price}, price={price}, executed={executed_price}")

                # Тип заявки
                order_type_raw = getattr(order_resp, "order_type", "")
                order_type = "buy" if (isinstance(order_type_raw, int) and order_type_raw == 1) else "sell"
                if isinstance(order_type_raw, str):
                    order_type = order_type_raw.lower()

                # Статус
                status_raw = getattr(order_resp, "status", "")
                status = get_order_status_name(status_raw)

                orders.append(Order(
                    order_id=getattr(order_resp, "order_id", ""),
                    figi=figi,
                    instrument_uid=instrument_uid,
                    ticker=ticker,
                    name=name,
                    order_type=order_type,
                    status=status,
                    lots_requested=float(getattr(order_resp, "lots_requested", 0) or 0),
                    lots_executed=float(getattr(order_resp, "lots_executed", 0) or 0),
                    price=price,
                    executed_order_price=executed_price,
                    created=getattr(order_resp, "created", None),
                    updated=getattr(order_resp, "updated", None),
                ))

        except Exception as e:
            print(f"[get_orders] Ошибка: {e}")
            import traceback
            traceback.print_exc()

    # Сортируем по дате обновления (новые сначала)
    orders.sort(key=lambda x: x.updated or x.created or datetime.now(timezone.utc), reverse=True)
    return orders


# ============================================================================
# Кэширование заявок на диск
# ============================================================================

ORDERS_CACHE_DIR = DATA_DIR / "real_account_orders"


def get_orders_cache_path(account_id: str) -> Path:
    """Получить путь к файлу кэша заявок."""
    ORDERS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_account_id = account_id.replace("-", "_").replace(".", "_")
    return ORDERS_CACHE_DIR / f"{safe_account_id}_orders.json"


def save_orders_to_cache(account_id: str, orders: list[Order]) -> Path:
    """Сохранить заявки в кэш."""
    path = get_orders_cache_path(account_id)

    data = {
        "account_id": account_id,
        "updated": datetime.now(timezone.utc).isoformat(),
        "orders": [
            {
                "order_id": o.order_id,
                "figi": o.figi,
                "instrument_uid": o.instrument_uid,
                "ticker": o.ticker,
                "name": o.name,
                "order_type": o.order_type,
                "status": o.status,
                "lots_requested": o.lots_requested,
                "lots_executed": o.lots_executed,
                "price": o.price,
                "executed_order_price": o.executed_order_price,
                "created": o.created.isoformat() if o.created else None,
                "updated": o.updated.isoformat() if o.updated else None,
            }
            for o in orders
        ]
    }

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_orders_from_cache(account_id: str) -> list[Order]:
    """Загрузить заявки из кэша."""
    path = get_orders_cache_path(account_id)

    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        orders = []

        for item in data.get("orders", []):
            # Парсим даты
            created = None
            updated = None
            if item.get("created"):
                try:
                    created = datetime.fromisoformat(item["created"])
                except Exception:
                    pass
            if item.get("updated"):
                try:
                    updated = datetime.fromisoformat(item["updated"])
                except Exception:
                    pass

            orders.append(Order(
                order_id=item.get("order_id", ""),
                figi=item.get("figi", ""),
                instrument_uid=item.get("instrument_uid", ""),
                ticker=item.get("ticker"),
                name=item.get("name"),
                order_type=item.get("order_type", ""),
                status=item.get("status", ""),
                lots_requested=float(item.get("lots_requested", 0)),
                lots_executed=float(item.get("lots_executed", 0)),
                price=float(item.get("price", 0)),
                executed_order_price=float(item.get("executed_order_price", 0)),
                created=created,
                updated=updated,
            ))

        return orders
    except Exception as e:
        print(f"[load_orders_from_cache] Ошибка: {e}")
        return []


def clear_orders_cache():
    """Очистить кэш заявок."""
    import shutil
    if ORDERS_CACHE_DIR.exists():
        shutil.rmtree(ORDERS_CACHE_DIR)
        ORDERS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
