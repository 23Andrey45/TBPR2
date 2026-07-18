from __future__ import annotations

import threading
import traceback
from datetime import datetime, timezone
from queue import Queue
from time import perf_counter
from typing import Optional

from PyQt6 import QtCore
from t_tech.invest import Client

from core.instruments_catalog import InstrumentInfo
from tabs.instruments_controller import InstrumentsController
from workers import TradingStatusLoader


class _QuotesWorker(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # dict: {"seq": int, "prices": dict[str, float], "by_figi": dict[str, float]}
    error = QtCore.pyqtSignal(str)

    REQUEST_TIMEOUT_SEC = 8.0

    def __init__(self, token: str):
        super().__init__()
        self.token = token
        self._stopping = False

    @QtCore.pyqtSlot()
    def stop(self):
        self._stopping = True

    @QtCore.pyqtSlot(int, object)
    def fetch(self, seq: int, key_and_figi: list[tuple[str, str]]):
        if self._stopping:
            return
        if not key_and_figi:
            self.loaded.emit({"seq": seq, "prices": {}, "by_figi": {}})
            return

        result_queue: Queue = Queue(maxsize=1)

        def _task():
            try:
                prices, by_figi = self._load_prices(key_and_figi)
                result_queue.put((prices, by_figi, None))
            except Exception:
                result_queue.put((None, None, traceback.format_exc()))

        call_thread = threading.Thread(target=_task, daemon=True)
        call_thread.start()
        call_thread.join(timeout=self.REQUEST_TIMEOUT_SEC)

        if call_thread.is_alive():
            self.error.emit(
                f"quotes request timeout after {self.REQUEST_TIMEOUT_SEC:.1f}s "
                f"(payload={len(key_and_figi)})"
            )
            return

        prices, by_figi, err = result_queue.get()
        if err:
            self.error.emit(err)
            return

        self.loaded.emit({"seq": seq, "prices": prices, "by_figi": by_figi})

    def _load_prices(self, key_and_figi: list[tuple[str, str]]) -> tuple[dict[str, float], dict[str, float]]:
        figi_to_key = {figi: key for key, figi in key_and_figi}
        figis = [figi for _, figi in key_and_figi]
        out: dict[str, float] = {}
        by_figi: dict[str, float] = {}

        with Client(token=self.token) as client:
            resp = client.market_data.get_last_prices(figi=figis)
            for lp in getattr(resp, "last_prices", []) or []:
                figi = str(getattr(lp, "figi", "") or "")
                key = figi_to_key.get(figi)
                if not key:
                    continue

                p = getattr(lp, "price", None)
                if p is None:
                    continue

                units = int(getattr(p, "units", 0) or 0)
                nano = int(getattr(p, "nano", 0) or 0)
                price = units + nano / 1e9
                out[key] = price
                by_figi[figi] = price

        return out, by_figi


class QuotesHub(QtCore.QObject):
    quotes_updated = QtCore.pyqtSignal(object)  # dict[str, float], key = InstrumentInfo.fav_key()
    trading_status_updated = QtCore.pyqtSignal(object)  # dict[str, dict] - статусы по FIGI
    error = QtCore.pyqtSignal(str)

    # Bridge signal to worker thread.
    _request_fetch = QtCore.pyqtSignal(int, object)
    _request_status_fetch = QtCore.pyqtSignal(list)  # list of FIGI

    def __init__(self, token: str, instruments_controller: InstrumentsController, parent=None):
        super().__init__(parent)
        self.token = token
        self.instruments_controller = instruments_controller
        self._prices: dict[str, float] = {}
        self._prices_by_figi: dict[str, float] = {}
        self._trading_statuses: dict[str, dict] = {}  # FIGI -> status info
        self._refresh_seq = 0
        self._in_flight = False
        self._status_in_flight = False

        # Поток для котировок
        self._thread = QtCore.QThread(self)
        self._worker = _QuotesWorker(self.token)
        self._worker.moveToThread(self._thread)
        self._thread.start()

        self._request_fetch.connect(self._worker.fetch)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.error.connect(self._on_worker_error)

        self._timer = QtCore.QTimer(self)
        # ✅ ИСПРАВЛЕНИЕ: Увеличиваем интервал с 3000 до 10000 мс
        self._timer.setInterval(10000)
        self._timer.timeout.connect(self.request_refresh)

        # ✅ Таймер для проверки статусов торгов (раз в минуту)
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setInterval(60000)
        self._status_timer.timeout.connect(self.request_status_refresh)

        # ✅ Поток для статусов торгов
        self._status_thread = QtCore.QThread(self)
        self._status_worker = TradingStatusLoader(self.token, [])
        self._status_worker.moveToThread(self._status_thread)
        self._status_thread.start()

        # ✅ Подключение с правильным типом соединения
        self._request_status_fetch.connect(
            self._status_worker.run,
            QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._status_worker.loaded.connect(self._on_status_loaded)
        self._status_worker.error.connect(self._on_status_error)

        self._dbg("Status worker initialized")

        # ✅ Запрос статусов при обновлении избранного
        self.instruments_controller.favorites_updated.connect(self._on_favorites_updated_for_status)
        self.instruments_controller.favorites_updated.connect(lambda *_: self.request_refresh())

        self._dbg("Connected to favorites_updated signal")

    def _on_favorites_updated_for_status(self, favorites):
        """Вызвать request_status_refresh с задержкой."""
        self._dbg(f"_on_favorites_updated_for_status: {len(favorites)} favorites")
        QtCore.QTimer.singleShot(1000, self.request_status_refresh)

    @QtCore.pyqtSlot(object)
    def _on_loaded(self, payload: dict):
        seq = int(payload.get("seq", 0) or 0)
        prices = payload.get("prices", {}) or {}
        by_figi = payload.get("by_figi", {}) or {}

        if seq != self._refresh_seq:
            self._dbg(f"ignore stale payload seq={seq}, current={self._refresh_seq}")
            return

        self._in_flight = False
        dt = perf_counter() - getattr(self, "_sent_at", perf_counter())

        if prices:
            self._prices.update(prices)
            if by_figi:
                self._prices_by_figi.update(by_figi)

            # Keep key-based cache synchronized with current favorites through FIGI mapping.
            for info in self.instruments_controller.favorites():
                figi = (info.figi or info.instrument_id or "").strip()
                if not figi:
                    continue
                p = self._prices_by_figi.get(figi)
                if p is not None:
                    self._prices[info.fav_key()] = p

            self.quotes_updated.emit(dict(self._prices))

            # ✅ После загрузки цен - запрашиваем статусы
            if not self._status_in_flight:
                self._dbg("_on_loaded: requesting status refresh")
                QtCore.QTimer.singleShot(500, self.request_status_refresh)

            # self._dbg(f"loaded prices={len(prices)} cached={len(self._prices)} in {dt:.3f}s")
            return

        self._dbg(f"loaded empty prices in {dt:.3f}s")

    def start(self):
        self._dbg("start")
        self._timer.start()
        self._status_timer.start()
        self.request_refresh()
        # ✅ Не вызываем request_status_refresh() здесь — будет вызван при favorites_updated

    def stop(self, wait_ms: int = 2000):
        self._dbg("stop")
        self._timer.stop()
        self._status_timer.stop()
        self._in_flight = False
        self._status_in_flight = False

        try:
            QtCore.QMetaObject.invokeMethod(self._worker, "stop", QtCore.Qt.ConnectionType.QueuedConnection)
        except Exception:
            pass

        self._thread.quit()
        self._thread.wait(wait_ms)

        # Остановка потока статусов
        if hasattr(self, '_status_thread') and self._status_thread:
            self._status_thread.quit()
            self._status_thread.wait(wait_ms)

    def _dbg(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[quotes-hub:{ts}] {msg}")

    def request_refresh(self):
        if self._in_flight:
            self._dbg("skip refresh: previous request is still running")
            return

        payload: list[tuple[str, str]] = []
        for info in self.instruments_controller.favorites():
            figi = (info.figi or info.instrument_id or "").strip()
            if figi:
                payload.append((info.fav_key(), figi))

        if not payload:
            # self._dbg("skip refresh: favorites payload is empty")
            return

        self._refresh_seq += 1
        self._in_flight = True
        self._sent_at = perf_counter()
        # self._dbg(f"refresh #{self._refresh_seq} payload={len(payload)}")
        self._request_fetch.emit(self._refresh_seq, payload)

    @QtCore.pyqtSlot(object)
    def _on_loaded(self, payload: dict):
        seq = int(payload.get("seq", 0) or 0)
        prices = payload.get("prices", {}) or {}
        by_figi = payload.get("by_figi", {}) or {}

        if seq != self._refresh_seq:
            self._dbg(f"ignore stale payload seq={seq}, current={self._refresh_seq}")
            return

        self._in_flight = False
        dt = perf_counter() - getattr(self, "_sent_at", perf_counter())

        if prices:
            self._prices.update(prices)
            if by_figi:
                self._prices_by_figi.update(by_figi)

            # Keep key-based cache synchronized with current favorites through FIGI mapping.
            for info in self.instruments_controller.favorites():
                figi = (info.figi or info.instrument_id or "").strip()
                if not figi:
                    continue
                p = self._prices_by_figi.get(figi)
                if p is not None:
                    self._prices[info.fav_key()] = p

            self.quotes_updated.emit(dict(self._prices))
            # self._dbg(f"loaded prices={len(prices)} cached={len(self._prices)} in {dt:.3f}s")
            return

        self._dbg(f"loaded empty prices in {dt:.3f}s")

    @QtCore.pyqtSlot(str)
    def _on_worker_error(self, err: str):
        self._in_flight = False
        self.error.emit(err)

    def get_price(self, info: InstrumentInfo) -> Optional[float]:
        p = self._prices.get(info.fav_key())
        if p is not None:
            return p

        figi = (info.figi or info.instrument_id or "").strip()
        if figi:
            p = self._prices_by_figi.get(figi)
            if p is not None:
                return p

        return None

    def get_price_text(self, info: InstrumentInfo) -> str:
        p = self.get_price(info)
        if p is None:
            return ""
        return f"{p:.6f}".rstrip("0").rstrip(".")

    # ✅ Методы для проверки статусов торгов

    def request_status_refresh(self):
        """Запросить обновление статусов торгов."""
        if self._status_in_flight:
            self._dbg("request_status_refresh: SKIP - in flight")
            return

        figis = []
        for info in self.instruments_controller.favorites():
            figi = (info.figi or info.instrument_id or "").strip()
            if figi:
                figis.append(figi)

        if not figis:
            self._dbg("request_status_refresh: SKIP - no figis")
            return

        self._status_in_flight = True
        self._dbg(f"request_status_refresh: {len(figis)} figis")
        self._request_status_fetch.emit(figis)
        self._dbg(f"request_status_fetch: emitted")

    @QtCore.pyqtSlot(object)
    def _on_status_loaded(self, statuses: dict):
        """Обработка полученных статусов."""
        self._status_in_flight = False
        self._trading_statuses = statuses
        self.trading_status_updated.emit(statuses)
        self._dbg(f"status loaded: {len(statuses)} statuses")
        for figi, status in list(statuses.items())[:3]:
            self._dbg(f"  {figi}: {status.get('trading_status', 'N/A')}")

    @QtCore.pyqtSlot(str)
    def _on_status_error(self, err: str):
        """Обработка ошибки статусов."""
        self._status_in_flight = False
        self._dbg(f"status error: {err}")
        import traceback
        traceback.print_exc()

    def get_trading_status(self, figi: str) -> dict:
        """Получить статус торгов по FIGI."""
        return self._trading_statuses.get(figi, {})

    def is_market_open(self, figi: str) -> bool:
        """Проверить, открыта ли биржа для данного FIGI."""
        status = self._trading_statuses.get(figi, {})
        return status.get('api_trade_available', False)
