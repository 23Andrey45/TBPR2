# core/instruments_utils.py
"""
Утилиты для работы с инструментами.
"""

from __future__ import annotations

from typing import Any, Optional

from core.instruments_catalog import InstrumentInfo


def get_ticker_by_figi(
        figi: str,
        by_figi: dict[str, InstrumentInfo],
        orders_cache: Optional[list[dict[str, Any]]] = None,
) -> str:
    """
    Найти тикер по FIGI.

    Args:
        figi: FIGI инструмента
        by_figi: Словарь {figi: InstrumentInfo}
        orders_cache: Кэш ордеров для поиска (опционально)

    Returns:
        Тикер или FIGI если не найден
    """
    if figi in by_figi:
        return by_figi[figi].ticker

    # Ищем в кэше ордеров
    if orders_cache:
        for rec in orders_cache:
            if rec.get("figi") == figi:
                return rec.get("ticker", figi)

    return figi


def build_figi_index(instruments: list[InstrumentInfo]) -> dict[str, InstrumentInfo]:
    """
    Построить индекс {figi: InstrumentInfo}.

    Args:
        instruments: Список инструментов

    Returns:
        Словарь {figi: InstrumentInfo}
    """
    return {info.figi: info for info in instruments if info.figi}