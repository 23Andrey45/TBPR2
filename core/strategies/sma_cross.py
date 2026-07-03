# core/strategies/sma_cross.py
from __future__ import annotations

from core.strategies.base import Strategy, ParamSpec, StrategyResult


class SmaCrossStrategy(Strategy):
    @property
    def strategy_id(self) -> str:
        return "sma_cross"

    @property
    def strategy_name(self) -> str:
        return "SMA cross (close)"

    def param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec("fast", "Fast SMA window", "int", 10, min=1, max=10_000),
            ParamSpec("slow", "Slow SMA window", "int", 30, min=2, max=10_000),
            ParamSpec("lot", "Размер лота (шт.)", "int", 1, min=1, max=1_000_000),
            ParamSpec("allow_short", "Разрешить шорт", "bool", False),
        ]

    def run(self, candles, params, context) -> StrategyResult:
        fast = params["fast"]
        slow = params["slow"]
        lot = params["lot"]
        allow_short = params["allow_short"]

        if fast >= slow:
            raise ValueError("fast должно быть < slow")
        if len(candles) < slow + 2:
            raise ValueError("Недостаточно свечей для SMA")

        closes = [c.close for c in candles]

        def sma(i: int, w: int) -> float:
            s = 0.0
            for k in range(i - w + 1, i + 1):
                s += closes[k]
            return s / w

        cash = 0.0
        position = 0  # в лотах (может стать -lot если allow_short)

        buys = 0
        sells = 0
        trades = 0

        # модель: если fast пересёк slow вверх -> target = +lot
        # если вниз -> target = -lot (если allow_short) иначе 0
        for i in range(slow, len(candles)):
            f = sma(i, fast)
            s = sma(i, slow)
            prev_f = sma(i - 1, fast)
            prev_s = sma(i - 1, slow)

            price = candles[i].close

            cross_up = prev_f <= prev_s and f > s
            cross_down = prev_f >= prev_s and f < s

            if cross_up:
                target = lot
            elif cross_down:
                target = -lot if allow_short else 0
            else:
                continue

            delta = target - position
            if delta == 0:
                continue

            # покупка delta>0, продажа delta<0
            if delta > 0:
                cash -= price * delta
                buys += delta
            else:
                cash += price * (-delta)
                sells += (-delta)

            position = target
            trades += 1

        last_price = candles[-1].close
        equity = cash + position * last_price

        metrics = {
            "Свечей": str(len(candles)),
            "fast": str(fast),
            "slow": str(slow),
            "allow_short": str(bool(allow_short)),
            "Сделок": str(trades),
            "Bought lots": str(buys),
            "Sold lots": str(sells),
            "Cash (баланс денег)": f"{cash:.4f}",
            "Финальная позиция (лоты)": str(position),
            "Equity / прибыль": f"{equity:.4f}",
        }

        return StrategyResult(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            params_used=params,
            metrics=metrics,
            extra={"trades_count": trades},
        )
