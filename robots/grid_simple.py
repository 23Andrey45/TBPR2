# core/robots/grid_simple.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Any

getcontext().prec = 28


def _round_to_tick(value: float, tick: float) -> float:
    if tick <= 0:
        return float(value)

    d = Decimal(str(value))
    t = Decimal(str(tick))
    k = d / t
    rk = k.to_integral_value(rounding=ROUND_HALF_UP)

    return float(rk * t)


def _round_decimal_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= 0:
        return value
    k = value / tick
    rk = k.to_integral_value(rounding=ROUND_HALF_UP)
    return rk * tick


def build_fixed_grid_levels(
    *,
    start_price: float,
    step_pct: float,
    steps_down: int,
    steps_up: int,
    tick_size: float,
) -> list[float]:
    step = Decimal(str(max(0.0001, float(step_pct)))) / Decimal("100")
    tick = Decimal(str(max(0.0, float(tick_size))))
    start = Decimal(str(float(start_price)))
    start = _round_decimal_to_tick(start, tick)

    above = []
    up = start
    for _ in range(steps_up):
        up = up * (Decimal("1") + step)
        above.append(_round_decimal_to_tick(up, tick))
    above = list(reversed(above))

    below = []
    down = start
    for _ in range(steps_down):
        down = down * (Decimal("1") - step)
        below.append(_round_decimal_to_tick(down, tick))

    levels = above + [start] + below

    # Убираем дубликаты, если шаг меньше минимального тика.
    out: list[float] = []
    seen: set[str] = set()
    for p in levels:
        key = f"{float(p):.9f}"
        if key in seen:
            continue
        seen.add(key)
        out.append(float(p))

    # Сетка всегда в порядке убывания.
    out.sort(reverse=True)
    return out


def build_grid_view_rows(
    *,
    levels: list[float],
    last_trade_price: float,
    current_price: float,
) -> list[dict[str, Any]]:
    if not levels:
        return []

    prices = sorted([float(x) for x in levels], reverse=True)
    last_trade_price = float(last_trade_price)
    current_price = float(current_price)

    # Привязываем последнюю сделку к ближайшему уровню сетки.
    base_idx = min(range(len(prices)), key=lambda i: abs(prices[i] - last_trade_price))

    markers = ["" for _ in prices]
    colors = ["none" for _ in prices]

    markers[base_idx] = f"{last_trade_price:.6f}".rstrip("0").rstrip(".")

    if current_price > last_trade_price and base_idx > 0:
        markers[base_idx - 1] = f"{current_price:.6f}".rstrip("0").rstrip(".")
        colors[base_idx - 1] = "up"
    elif current_price < last_trade_price and base_idx < len(prices) - 1:
        markers[base_idx + 1] = f"{current_price:.6f}".rstrip("0").rstrip(".")
        colors[base_idx + 1] = "down"

    out: list[dict[str, Any]] = []
    for idx, price in enumerate(prices):
        out.append(
            {
                "idx": idx,
                "price": float(price),
                "marker": markers[idx],
                "marker_color": colors[idx],
            }
        )
    return out


def build_grid_rows(
    *,
    last_trade_price: float,
    current_price: float,
    step_pct: float,
    steps_down: int,
    steps_up: int,
) -> list[dict[str, Any]]:
    # Backward-compatible обертка (без учета тика).
    levels = build_fixed_grid_levels(
        start_price=last_trade_price,
        step_pct=step_pct,
        steps_down=steps_down,
        steps_up=steps_up,
        tick_size=0.0,
    )
    return build_grid_view_rows(
        levels=levels,
        last_trade_price=last_trade_price,
        current_price=current_price,
    )