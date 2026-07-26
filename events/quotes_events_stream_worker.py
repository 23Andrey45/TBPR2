from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from PyQt6 import QtCore
from t_tech.invest import AsyncClient
from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX

try:
    from t_tech.invest import (
        LastPriceInstrument,
        MarketDataRequest,
        SubscribeLastPriceRequest,
        SubscriptionAction,
    )
except Exception:
    LastPriceInstrument = None
    MarketDataRequest = None
    SubscribeLastPriceRequest = None
    SubscriptionAction = None


class QuotesEventsStreamWorker(QtCore.QObject):
    quote_received = QtCore.pyqtSignal(object)
    status_changed = QtCore.pyqtSignal(str)
    subscription_info = QtCore.pyqtSignal(object)
    stream_closed = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, figis: list[str]):
        super().__init__()
        self.token = token
        self.figis = [str(x).strip() for x in figis if str(x).strip()]
        self._stop_requested = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._active_meta: dict[str, str] | None = None

    @QtCore.pyqtSlot()
    def stop(self) -> None:
        self._stop_requested = True
        self.status_changed.emit("Запрошена остановка quotes stream...")

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            asyncio.run(self._run_async())
        except Exception:
            self.status_changed.emit(traceback.format_exc())
        finally:
            self._loop = None
            self.finished.emit()

    async def _run_async(self) -> None:
        self._loop = asyncio.get_running_loop()

        if not self.figis:
            self.status_changed.emit("Нет FIGI для подписки на котировки")
            return

        if None in (LastPriceInstrument, MarketDataRequest, SubscribeLastPriceRequest, SubscriptionAction):
            self.status_changed.emit("SDK не поддерживает market data stream классы")
            return

        errors: list[str] = []
        for target in (INVEST_GRPC_API_SANDBOX, INVEST_GRPC_API):
            if self._stop_requested:
                return
            try:
                ok = await self._run_for_target(str(target))
                if ok:
                    return
            except Exception as exc:
                errors.append(f"target={target}: {exc}")

        self.status_changed.emit("Quotes stream не запущен: " + " | ".join(errors))

    async def _run_for_target(self, target: str) -> bool:
        self.status_changed.emit(f"Quotes stream target: {target}")
        async with AsyncClient(self.token, target=target) as client:
            stream_service = getattr(client, "market_data_stream", None)
            if stream_service is None or not hasattr(stream_service, "market_data_stream"):
                raise RuntimeError("В SDK не найден client.market_data_stream.market_data_stream")

            meta = {
                "target": target,
                "service": "market_data_stream",
                "method": "market_data_stream",
                "figis": ",".join(self.figis[:20]),
                "figis_count": str(len(self.figis)),
            }
            self._active_meta = meta
            self.subscription_info.emit(meta)

            iterator = self._request_iterator()
            stream = stream_service.market_data_stream(iterator)

            ait = stream.__aiter__()
            next_task = asyncio.create_task(anext(ait))
            while True:
                if self._stop_requested:
                    if not next_task.done():
                        next_task.cancel()
                    break

                done, _ = await asyncio.wait({next_task}, timeout=0.5)
                if not done:
                    continue

                try:
                    msg = next_task.result()
                except StopAsyncIteration:
                    break
                except asyncio.CancelledError:
                    break

                self.quote_received.emit(self._to_quote_event(msg))
                next_task = asyncio.create_task(anext(ait))

            self.stream_closed.emit(
                {
                    **meta,
                    "reason": "stop_requested" if self._stop_requested else "stream_finished",
                    "closed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return True

    async def _request_iterator(self) -> AsyncIterator[Any]:
        subscribe_action = getattr(SubscriptionAction, "SUBSCRIPTION_ACTION_SUBSCRIBE")
        unsubscribe_action = getattr(SubscriptionAction, "SUBSCRIPTION_ACTION_UNSUBSCRIBE", None)

        instruments = [LastPriceInstrument(figi=figi) for figi in self.figis]
        subscribe_req = MarketDataRequest(
            subscribe_last_price_request=SubscribeLastPriceRequest(
                subscription_action=subscribe_action,
                instruments=instruments,
            )
        )
        yield subscribe_req

        while not self._stop_requested:
            await asyncio.sleep(0.5)

        if unsubscribe_action is not None:
            unsubscribe_req = MarketDataRequest(
                subscribe_last_price_request=SubscribeLastPriceRequest(
                    subscription_action=unsubscribe_action,
                    instruments=instruments,
                )
            )
            yield unsubscribe_req

    def _to_quote_event(self, msg: Any) -> dict[str, str]:
        event_type = "market_data"
        figi = ""
        price = ""
        msg_time = ""

        last_price = getattr(msg, "last_price", None)
        if last_price is not None:
            event_type = "last_price"
            figi = str(getattr(last_price, "figi", "") or "")
            q = getattr(last_price, "price", None)
            if q is not None:
                units = int(getattr(q, "units", 0) or 0)
                nano = int(getattr(q, "nano", 0) or 0)
                val = units + nano / 1e9
                price = f"{val:.6f}".rstrip("0").rstrip(".")
            t = getattr(last_price, "time", None)
            if t is not None:
                msg_time = str(t)

        if hasattr(msg, "ping") and getattr(msg, "ping"):
            event_type = "ping"

        return {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "figi": figi,
            "price": price,
            "time": msg_time,
            "payload": self._msg_preview(msg),
        }

    def _msg_preview(self, msg: Any) -> str:
        text = str(msg)
        text = " ".join(text.split())
        return text[:500]
