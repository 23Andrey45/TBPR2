from __future__ import annotations

import asyncio
import inspect
import traceback
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from PyQt6 import QtCore
from t_tech.invest import AsyncClient
from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX

try:
    from t_tech.invest.grpc.orders_pb2 import OrderStateStreamRequest, TradesStreamRequest
except Exception:
    OrderStateStreamRequest = None
    TradesStreamRequest = None


class OrdersEventsStreamWorker(QtCore.QObject):
    event_received = QtCore.pyqtSignal(object)
    status_changed = QtCore.pyqtSignal(str)
    subscription_info = QtCore.pyqtSignal(object)
    stream_closed = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str):
        super().__init__()
        self.token = token
        self.account_id = (account_id or "").strip()
        self._stop_requested = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._active_stream: Any | None = None
        self._active_meta: dict[str, str] | None = None

    @QtCore.pyqtSlot()
    def stop(self) -> None:
        self._stop_requested = True
        self.status_changed.emit("Запрошена остановка stream...")
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._request_async_stop)

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

        if not self.account_id:
            self.status_changed.emit("Не задан account_id для stream")
            return

        self.status_changed.emit(f"Подключение stream для account_id={self.account_id}")

        errors: list[str] = []
        for target in (INVEST_GRPC_API_SANDBOX, INVEST_GRPC_API):
            if self._stop_requested:
                return

            try:
                ok = await self._run_for_target(target)
                if ok:
                    return
            except Exception as exc:
                errors.append(f"target={target}: {exc}")

        raise RuntimeError(
            "Не удалось запустить stream ни в sandbox, ни в prod. "
            + " | ".join(errors)
        )

    async def _run_for_target(self, target: str) -> bool:
        self.status_changed.emit(f"Пробую target: {target}")

        async with AsyncClient(self.token, target=target) as client:
            stream_service = getattr(client, "orders_stream", None)
            if stream_service is None:
                raise RuntimeError("В SDK не найден client.orders_stream")

            for method_name in ("order_state_stream", "trades_stream"):
                if self._stop_requested:
                    return True
                if not hasattr(stream_service, method_name):
                    continue

                ok = await self._consume_stream_method(stream_service, method_name, target)
                if ok:
                    return True

        return False

    async def _consume_stream_method(self, stream_service: Any, method_name: str, target: str) -> bool:
        method = getattr(stream_service, method_name)
        self.status_changed.emit(f"Пробую stream метод: {method_name}")

        attempts: list[tuple[str, Any]] = [
            ("kwargs_accounts", lambda: method(accounts=[self.account_id])),
            ("arg_iterator", lambda: method(self._request_iterator(method_name))),
            (
                "kwarg_iterator",
                lambda: method(request_iterator=self._request_iterator(method_name)),
            ),
        ]

        last_error = ""
        for attempt_name, builder in attempts:
            if self._stop_requested:
                return True

            try:
                stream = builder()
                meta = {
                    "account_id": self.account_id,
                    "target": str(target),
                    "service": "orders_stream",
                    "method": method_name,
                    "attempt": attempt_name,
                }
                self._active_stream = stream
                self._active_meta = meta
                self.subscription_info.emit(meta)

                iterator = stream.__aiter__()
                next_task = asyncio.create_task(anext(iterator))
                while True:
                    if self._stop_requested:
                        if not next_task.done():
                            next_task.cancel()
                        await self._close_active_stream(reason="stop_requested")
                        return True

                    try:
                        done, _ = await asyncio.wait({next_task}, timeout=0.5)
                        if not done:
                            continue
                        msg = next_task.result()
                        next_task = asyncio.create_task(anext(iterator))
                    except StopAsyncIteration:
                        break
                    except asyncio.CancelledError:
                        continue

                    self.event_received.emit(self._to_event_dict(method_name, msg))

                await self._close_active_stream(reason="stream_finished")
                return True
            except TypeError as exc:
                last_error = f"{attempt_name}: {exc}"
                self._active_stream = None
                self._active_meta = None
                continue
            except Exception as exc:
                last_error = f"{attempt_name}: {exc}"
                self._active_stream = None
                self._active_meta = None
                break

        self.status_changed.emit(f"Метод {method_name} не запущен ({last_error})")
        return False

    async def _request_iterator(self, method_name: str) -> AsyncIterator[Any]:
        req = self._make_request(method_name)
        if req is not None:
            yield req

        # Keep stream open while worker is alive.
        while not self._stop_requested:
            await asyncio.sleep(1.0)

    def _request_async_stop(self) -> None:
        self._stop_requested = True
        if self._loop is not None:
            try:
                self._loop.create_task(self._close_active_stream(reason="external_stop"))
            except RuntimeError:
                pass

    async def _close_active_stream(self, reason: str) -> None:
        stream = self._active_stream
        meta = dict(self._active_meta or {})
        if stream is None:
            return

        close_method = ""
        close_error = ""
        for name in ("cancel", "aclose", "close"):
            if not hasattr(stream, name):
                continue
            try:
                result = getattr(stream, name)()
                if inspect.isawaitable(result):
                    await result
                close_method = name
                break
            except Exception as exc:
                close_error = str(exc)

        meta.update(
            {
                "reason": reason,
                "close_method": close_method or "none",
                "close_error": close_error,
                "closed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.stream_closed.emit(meta)
        self._active_stream = None
        self._active_meta = None

    def _make_request(self, method_name: str) -> Any | None:
        req = None

        if method_name == "trades_stream" and TradesStreamRequest is not None:
            req = TradesStreamRequest()
        if method_name == "order_state_stream" and OrderStateStreamRequest is not None:
            req = OrderStateStreamRequest()

        if req is None:
            return None

        if hasattr(req, "accounts"):
            try:
                req.accounts.append(self.account_id)
            except Exception:
                try:
                    req.accounts.extend([self.account_id])
                except Exception:
                    pass
        elif hasattr(req, "account_id"):
            setattr(req, "account_id", self.account_id)

        return req

    def _to_event_dict(self, method_name: str, msg: Any) -> dict[str, str]:
        now = datetime.now(timezone.utc).isoformat()
        event_type = method_name
        order_id = ""
        status = ""
        payload = self._msg_preview(msg)

        for field_name in ("order_id", "orderId", "trade_order_id"):
            if hasattr(msg, field_name):
                value = getattr(msg, field_name)
                if value:
                    order_id = str(value)
                    break

        for field_name in ("execution_report_status", "order_execution_report_status", "status"):
            if hasattr(msg, field_name):
                value = getattr(msg, field_name)
                if value is not None:
                    status = str(value)
                    break

        if hasattr(msg, "ping") and getattr(msg, "ping"):
            event_type = "ping"

        return {
            "received_at": now,
            "event_type": event_type,
            "order_id": order_id,
            "status": status,
            "payload": payload,
        }

    def _msg_preview(self, msg: Any) -> str:
        text = str(msg)
        text = " ".join(text.split())
        return text[:500]
