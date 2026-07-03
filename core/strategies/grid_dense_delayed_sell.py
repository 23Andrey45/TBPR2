from __future__ import annotations

from core.strategies.base import Strategy, ParamSpec, StrategyResult, StrategyContext
from core.trading_logic import CandleData, Trade
from core.dividends_calc import calc_paid_dividends_in_range


def _simulate_dense_delayed_buy_sell(
    candles: list[CandleData],
    *,
    buy_step: float,
    buy_trigger: float,
    sell_trigger: float,
    sell_step: float,
    trade_lots: int,
    lot_size: int,
) -> dict:
    """
    Асимметричная плотная сетка с задержками старта:

    Базовая идея:
      ref_price = цена последней сделки (BUY или SELL)

    Покупки:
      - пока BUY-режим не активирован, ждём падения до ref*(1-buy_trigger)
        первая покупка на этом уровне
      - после активации покупаем каждые buy_step ниже (лотами)

    Продажи:
      - пока SELL-режим не активирован, ждём роста до ref*(1+sell_trigger)
        первая продажа на этом уровне
      - после активации продаём каждые sell_step выше (лотами)

    При смене направления режим противоположной стороны сбрасывается.

    Позиция: в лотах
    Деньги: price(за 1 бумагу) * (lots * lot_size)
    """
    if not candles:
        raise ValueError("Нет свечей")

    buy_step = float(buy_step)
    buy_trigger = float(buy_trigger)
    sell_trigger = float(sell_trigger)
    sell_step = float(sell_step)
    trade_lots = int(trade_lots)
    lot_size = int(lot_size or 1)

    if buy_step <= 0:
        raise ValueError("buy_step должно быть > 0")
    if buy_trigger <= 0:
        raise ValueError("buy_trigger должно быть > 0")
    if sell_trigger <= 0:
        raise ValueError("sell_trigger должно быть > 0")
    if sell_step <= 0:
        raise ValueError("sell_step должно быть > 0")
    if trade_lots <= 0:
        raise ValueError("trade_lots должно быть > 0")

    trades: list[Trade] = []
    cash = 0.0
    position_lots = 0

    buys = 0
    sells = 0

    max_pos = 0
    min_pos = 0
    min_cash = 0.0
    max_cash = 0.0

    # стартовая сделка (как и раньше): BUY по open первой свечи
    first = candles[0]
    ref_price = first.open

    cash -= ref_price * (trade_lots * lot_size)
    position_lots += trade_lots
    buys += trade_lots
    trades.append(Trade(time=first.time, side="BUY", price=ref_price, pos_after=position_lots))

    max_pos = max(max_pos, position_lots)
    min_pos = min(min_pos, position_lots)
    min_cash = min(min_cash, cash)
    max_cash = max(max_cash, cash)

    # режимы/уровни
    buy_active = False
    sell_active = False
    next_buy = None   # следующий BUY уровень (когда buy_active)
    next_sell = None  # следующий SELL уровень (когда sell_active)

    def buy_activate_level() -> float:
        return ref_price * (1.0 - buy_trigger)

    def sell_activate_level() -> float:
        return ref_price * (1.0 + sell_trigger)

    def process_down_segment(t, a: float, b: float):
        nonlocal cash, position_lots, buys, ref_price, buy_active, sell_active, next_buy, next_sell
        nonlocal max_pos, min_pos, min_cash, max_cash

        seg_lo, seg_hi = b, a  # a > b

        # 1) если buy не активен — проверяем активационный уровень
        if not buy_active:
            act = buy_activate_level()
            if seg_lo <= act <= seg_hi:
                level = act
                cash -= level * (trade_lots * lot_size)
                position_lots += trade_lots
                buys += trade_lots

                ref_price = level
                buy_active = True
                sell_active = False
                next_sell = None
                next_buy = ref_price * (1.0 - buy_step)

                trades.append(Trade(time=t, side="BUY", price=level, pos_after=position_lots))

                max_pos = max(max_pos, position_lots)
                min_pos = min(min_pos, position_lots)
                min_cash = min(min_cash, cash)
                max_cash = max(max_cash, cash)

        # 2) если buy активен — докупаем с частотой buy_step
        while buy_active and next_buy is not None:
            level = next_buy
            if not (seg_lo <= level <= seg_hi):
                break

            cash -= level * (trade_lots * lot_size)
            position_lots += trade_lots
            buys += trade_lots

            ref_price = level
            next_buy = ref_price * (1.0 - buy_step)

            trades.append(Trade(time=t, side="BUY", price=level, pos_after=position_lots))

            max_pos = max(max_pos, position_lots)
            min_pos = min(min_pos, position_lots)
            min_cash = min(min_cash, cash)
            max_cash = max(max_cash, cash)

    def process_up_segment(t, a: float, b: float):
        nonlocal cash, position_lots, sells, ref_price, buy_active, sell_active, next_buy, next_sell
        nonlocal max_pos, min_pos, min_cash, max_cash

        seg_lo, seg_hi = a, b  # b > a

        # 1) если sell не активен — проверяем активационный уровень
        if not sell_active:
            act = sell_activate_level()
            if seg_lo <= act <= seg_hi:
                level = act
                cash += level * (trade_lots * lot_size)
                position_lots -= trade_lots
                sells += trade_lots

                ref_price = level
                sell_active = True
                buy_active = False
                next_buy = None
                next_sell = ref_price * (1.0 + sell_step)

                trades.append(Trade(time=t, side="SELL", price=level, pos_after=position_lots))

                max_pos = max(max_pos, position_lots)
                min_pos = min(min_pos, position_lots)
                min_cash = min(min_cash, cash)
                max_cash = max(max_cash, cash)

        # 2) если sell активен — продаём с частотой sell_step
        while sell_active and next_sell is not None:
            level = next_sell
            if not (seg_lo <= level <= seg_hi):
                break

            cash += level * (trade_lots * lot_size)
            position_lots -= trade_lots
            sells += trade_lots

            ref_price = level
            next_sell = ref_price * (1.0 + sell_step)

            trades.append(Trade(time=t, side="SELL", price=level, pos_after=position_lots))

            max_pos = max(max_pos, position_lots)
            min_pos = min(min_pos, position_lots)
            min_cash = min(min_cash, cash)
            max_cash = max(max_cash, cash)

    for c in candles:
        o, h, l, cl = c.open, c.high, c.low, c.close
        path = [o, h, l, cl] if cl >= o else [o, l, h, cl]

        for p0, p1 in zip(path, path[1:]):
            if p1 > p0:
                process_up_segment(c.time, p0, p1)
            elif p1 < p0:
                process_down_segment(c.time, p0, p1)

    last_price = candles[-1].close
    equity = cash + position_lots * last_price * lot_size
    max_invested = max(0.0, -min_cash)

    return dict(
        cash=cash,
        equity=equity,
        position_lots=position_lots,
        trades=trades,
        buys=buys,
        sells=sells,
        max_pos=max_pos,
        min_pos=min_pos,
        min_cash=min_cash,
        max_cash=max_cash,
        last_price=last_price,
        max_invested=max_invested,
    )


class GridDenseDelayedSellStrategy(Strategy):
    @property
    def strategy_id(self) -> str:
        return "grid_dense_delayed_sell"

    @property
    def strategy_name(self) -> str:
        return "Grid: плотная сетка + задержка BUY/SELL"

    def param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec("buy_step", "Buy step (0.001 = 0.1%)", "float", 0.001, min=0.00001, max=0.5),
            ParamSpec("buy_trigger", "Buy trigger (0.011 = 1.1%)", "float", 0.011, min=0.00001, max=1.0),
            ParamSpec("sell_trigger", "Sell trigger (0.01 = 1%)", "float", 0.01, min=0.00001, max=1.0),
            ParamSpec("sell_step", "Sell step (0.001 = 0.1%)", "float", 0.001, min=0.00001, max=1.0),
            ParamSpec("lot", "Размер сделки (лоты)", "int", 1, min=1, max=1_000_000),
        ]

    def run(self, candles, params: dict, context: StrategyContext) -> StrategyResult:
        inst = context.instrument
        lot_size = int(getattr(inst, "lot", 1) or 1)

        sim = _simulate_dense_delayed_buy_sell(
            candles,
            buy_step=params["buy_step"],
            buy_trigger=params["buy_trigger"],
            sell_trigger=params["sell_trigger"],
            sell_step=params["sell_step"],
            trade_lots=params["lot"],
            lot_size=lot_size,
        )

        metrics = {
            "Свечей": str(len(candles)),
            "Сделок всего": str(len(sim["trades"])),
            "Покупок (лоты)": str(sim["buys"]),
            "Продаж (лоты)": str(sim["sells"]),
            "Cash (баланс денег)": f'{sim["cash"]:.4f}',
            "Equity / прибыль": f'{sim["equity"]:.4f}',
            "Финальная позиция (лоты)": str(sim["position_lots"]),
            "Макс. позиция (лоты)": str(sim["max_pos"]),
            "Мин. позиция (лоты)": str(sim["min_pos"]),
            "Макс. вложение (денег)": f'{sim["max_invested"]:.4f}',
        }

        return StrategyResult(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            params_used=params,
            metrics=metrics,
            extra={"trades": sim["trades"]},
        )


class GridDenseDelayedSellDividendsStrategy(Strategy):
    @property
    def strategy_id(self) -> str:
        return "grid_dense_delayed_sell_div"

    @property
    def strategy_name(self) -> str:
        return "Grid: плотная сетка + задержка BUY/SELL + дивиденды(paid)"

    def param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec("buy_step", "Buy step (0.001 = 0.1%)", "float", 0.001, min=0.00001, max=0.5),
            ParamSpec("buy_trigger", "Buy trigger (0.011 = 1.1%)", "float", 0.011, min=0.00001, max=1.0),
            ParamSpec("sell_trigger", "Sell trigger (0.01 = 1%)", "float", 0.01, min=0.00001, max=1.0),
            ParamSpec("sell_step", "Sell step (0.001 = 0.1%)", "float", 0.001, min=0.00001, max=1.0),
            ParamSpec("lot", "Размер сделки (лоты)", "int", 1, min=1, max=1_000_000),
        ]

    def run(self, candles, params: dict, context: StrategyContext) -> StrategyResult:
        inst = context.instrument
        kind = (getattr(inst, "kind", "") or "").lower()
        lot_size = int(getattr(inst, "lot", 1) or 1)

        sim = _simulate_dense_delayed_buy_sell(
            candles,
            buy_step=params["buy_step"],
            buy_trigger=params["buy_trigger"],
            sell_trigger=params["sell_trigger"],
            sell_step=params["sell_step"],
            trade_lots=params["lot"],
            lot_size=lot_size,
        )

        div_paid = 0.0
        if kind in ("share", "etf") and context.dividends and candles and hasattr(candles[0].time, "tzinfo"):
            div_res = calc_paid_dividends_in_range(
                context.dividends,
                sim["trades"],
                start_pos_lots=0,
                lot_size=lot_size,
                range_start=candles[0].time,
                range_end=candles[-1].time,
            )
            div_paid = div_res.paid

        equity_with_div = sim["equity"] + div_paid

        metrics = {
            "Свечей": str(len(candles)),
            "Equity (без див)": f'{sim["equity"]:.4f}',
            "Дивиденды (paid)": f"{div_paid:.4f}",
            "Equity (с див)": f"{equity_with_div:.4f}",
            "Сделок": str(len(sim["trades"])),
            "Финальная позиция (лоты)": str(sim["position_lots"]),
            "Макс. позиция (лоты)": str(sim["max_pos"]),
            "Мин. позиция (лоты)": str(sim["min_pos"]),
            "Макс. вложение (денег)": f'{sim["max_invested"]:.4f}',
        }

        return StrategyResult(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            params_used=params,
            metrics=metrics,
            extra={"trades": sim["trades"]},
        )
