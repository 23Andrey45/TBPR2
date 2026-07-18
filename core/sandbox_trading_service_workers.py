# core/sandbox_trading_service_workers.py
"""
Вспомогательные функции для sandbox воркеров.
Перенесено из tabs/ для общего доступа.
"""

from __future__ import annotations

import inspect
from typing import Any


def make_request_for_method(method):
    """Создать request объект для метода."""
    sig = inspect.signature(method)
    if "request" not in sig.parameters:
        return None
    default_req = sig.parameters["request"].default
    req_cls = type(default_req)
    try:
        return req_cls()
    except Exception:
        return default_req


def set_req_attr(obj: object, names: list[str], value: Any) -> bool:
    """Установить атрибут request объекта."""
    if obj is None:
        return False
    for name in names:
        if hasattr(obj, name):
            try:
                setattr(obj, name, value)
                return True
            except Exception:
                pass
    return False


def money_like_to_str(x: Any) -> str:
    """Преобразовать денежное значение в строку."""
    if x is None:
        return ""
    if hasattr(x, "units") and hasattr(x, "nano"):
        units = int(getattr(x, "units", 0) or 0)
        nano = int(getattr(x, "nano", 0) or 0)
        val = units + nano / 1e9
        return f"{val:.6f}".rstrip("0").rstrip(".")
    try:
        return str(float(x))
    except Exception:
        return str(x)
