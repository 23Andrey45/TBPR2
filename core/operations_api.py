# core/operations_api.py
"""
API для получения истории операций с реального счёта.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
import json
from pathlib import Path

from t_tech.invest import Client
from app.config import DATA_DIR

# Маппинг кодов типов операций T-Invest API
OPERATION_TYPE_MAP = {
    1: "buy",
    2: "sell",
    3: "dividend",
    4: "coupon",
    5: "redeem",
    6: "partialRedeem",
    7: "convert",
    8: "exchange",
    9: "typeDeposit",
    10: "typeWithdraw",
    11: "typeBuyCard",
    12: "typeSellCard",
    13: "typeCfa",
    14: "typeOther",
    15: "typeSpending",
    16: "typeIncome",
    17: "typeTransfer",
    18: "typeDelivery",
    19: "typeCommission",
    20: "typeTax",
    21: "typeCashback",
}


def get_operation_type_name(op_type) -> str:
    """Конвертировать код типа операции в строку."""
    if isinstance(op_type, str):
        return op_type
    if isinstance(op_type, int):
        return OPERATION_TYPE_MAP.get(op_type, f"type_{op_type}")
    if hasattr(op_type, "name"):
        return op_type.name
    if hasattr(op_type, "value"):
        val = op_type.value
        if isinstance(val, int):
            return OPERATION_TYPE_MAP.get(val, f"type_{val}")
        return str(val)
    return str(op_type)


@dataclass
class Operation:
    """Операция по счёту."""
    id: str
    date: datetime
    instrument_type: str
    figi: str
    instrument_uid: str
    operation_type: str  # "buy", "sell", "dividend" и т.д.
    ticker: Optional[str] = None
    name: Optional[str] = None
    quantity: float = 0.0
    price: float = 0.0
    amount: float = 0.0  # сумма операции
    currency: str = "RUB"


def get_operations(
        token: str,
        account_id: str,
        from_date: datetime,
        to_date: datetime,
) -> list[Operation]:
    """
    Получить историю операций за период.
    """
    operations = []

    with Client(token=token) as client:
        try:
            resp = client.operations.get_operations(
                account_id=account_id,
                from_=from_date,
                to=to_date,
            )

            for op in getattr(resp, "operations", []) or []:
                # Получаем информацию об инструменте
                figi = getattr(op, "figi", "")
                instrument_uid = getattr(op, "instrument_uid", "")
                ticker = None
                name = None

                # Пробуем получить информацию об инструменте
                try:
                    if instrument_uid:
                        # Сначала пробуем по instrument_uid
                        try:
                            ins_resp = client.instruments.get_instrument_by(id=instrument_uid, id_type="instrument_uid")
                            ticker = getattr(ins_resp, "ticker", None)
                            name = getattr(ins_resp, "name", None)
                        except Exception:
                            pass

                    # Если не получилось, пробуем по figi через find_instrument
                    if not ticker and figi:
                        try:
                            ins_resp = client.instruments.find_instrument(id=figi)
                            instruments = getattr(ins_resp, "instruments", []) or []
                            if instruments:
                                inst = instruments[0]
                                ticker = getattr(inst, "ticker", None)
                                name = getattr(inst, "name", None)
                        except Exception:
                            pass

                    # Если всё ещё нет ticker, используем figi как запасной вариант
                    if not ticker and figi:
                        ticker = figi

                except Exception as e:
                    print(f"[get_operations] Ошибка получения инфо об инструменте {figi}: {e}")
                    # Используем figi как ticker если не удалось получить
                    if figi:
                        ticker = figi

                # Конвертируем цену
                price = 0.0
                op_price = getattr(op, "price", None)
                if op_price:
                    price = float(getattr(op_price, "units", 0) or 0) + float(getattr(op_price, "nano", 0) or 0) / 1e9

                # Конвертируем сумму
                amount = 0.0
                op_amount = getattr(op, "amount", None)
                if op_amount:
                    amount = float(getattr(op_amount, "units", 0) or 0) + float(
                        getattr(op_amount, "nano", 0) or 0) / 1e9

                # Количество
                quantity = float(getattr(op, "quantity", 0) or 0)

                # Конвертируем тип операции из enum в строку
                op_type_raw = getattr(op, "operation_type", "")
                op_type_str = get_operation_type_name(op_type_raw)

                operations.append(Operation(
                    id=getattr(op, "id", ""),
                    date=getattr(op, "date", datetime.now()),
                    instrument_type=getattr(op, "instrument_type", ""),
                    figi=figi,
                    instrument_uid=getattr(op, "instrument_uid", ""),
                    ticker=ticker,
                    name=name,
                    operation_type=op_type_str,
                    quantity=quantity,
                    price=price,
                    amount=amount,
                    currency=getattr(op, "currency", "RUB"),
                ))

        except Exception as e:
            print(f"[get_operations] Ошибка: {e}")
            import traceback
            traceback.print_exc()

    # Сортируем по дате (новые сначала)
    operations.sort(key=lambda x: x.date, reverse=True)
    return operations


# ============================================================================
# Кэширование истории на диск
# ============================================================================

HISTORY_CACHE_DIR = DATA_DIR / "real_account_history"


def get_history_cache_path(account_id: str, figi: str) -> Path:
    """Получить путь к файлу кэша истории для инструмента."""
    HISTORY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Заменяем потенциально проблемные символы в account_id
    safe_account_id = account_id.replace("-", "_").replace(".", "_")
    return HISTORY_CACHE_DIR / f"{safe_account_id}_{figi}.json"


def save_operations_to_cache(account_id: str, figi: str, operations: list[Operation]) -> Path:
    """Сохранить операции в кэш."""
    path = get_history_cache_path(account_id, figi)

    data = {
        "account_id": account_id,
        "figi": figi,
        "updated": datetime.now(timezone.utc).isoformat(),
        "operations": [
            {
                "id": op.id,
                "date": op.date.isoformat() if hasattr(op.date, "isoformat") else str(op.date),
                "instrument_type": op.instrument_type,
                "figi": op.figi,
                "ticker": op.ticker,
                "name": op.name,
                "operation_type": op.operation_type,
                "quantity": op.quantity,
                "price": op.price,
                "amount": op.amount,
                "currency": op.currency,
            }
            for op in operations
        ]
    }

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_operations_from_cache(account_id: str, figi: str) -> list[Operation]:
    """Загрузить операции из кэша."""
    path = get_history_cache_path(account_id, figi)

    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        operations = []

        for item in data.get("operations", []):
            # Парсим дату
            date_str = item.get("date", "")
            try:
                date = datetime.fromisoformat(date_str)
            except Exception:
                date = datetime.now()

            operations.append(Operation(
                id=item.get("id", ""),
                date=date,
                instrument_type=item.get("instrument_type", ""),
                figi=item.get("figi", ""),
                instrument_uid=item.get("instrument_uid", ""),
                ticker=item.get("ticker"),
                name=item.get("name"),
                operation_type=item.get("operation_type", ""),
                quantity=float(item.get("quantity", 0)),
                price=float(item.get("price", 0)),
                amount=float(item.get("amount", 0)),
                currency=item.get("currency", "RUB"),
            ))

        return operations
    except Exception as e:
        print(f"[load_operations_from_cache] Ошибка: {e}")
        return []


def clear_history_cache():
    """Очистить весь кэш истории."""
    import shutil
    if HISTORY_CACHE_DIR.exists():
        shutil.rmtree(HISTORY_CACHE_DIR)
        HISTORY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
