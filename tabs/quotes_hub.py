# tabs/quotes_hub.py
from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Optional

from PyQt6 import QtCore
from t_tech.invest import Client

from core.instruments_catalog import InstrumentInfo
from tabs.instruments_controller import InstrumentsController


class _QuotesLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # dict[str, float]
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, key_and_figi: list[tuple[str, str]]):
        super().__init__()
        self.token = token
        self.key_and_figi = key_and_figi

    def _dbg(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[quotes:{ts}] {msg}")

    @QtCore.pyqtSlot()
    def run(self):
        t0 = perf_counter()
        self._dbg(f"worker start figis={len(self.key_and_figi)}")
        try:
            self.loaded.emit(self._load())
        except Exception:
            import traceback

            self.error.emit(traceback.format_exc())
        finally:
            dt = perf_counter() - t0
            self._dbg(f"worker finished in {dt:.3f}s")
            self.finished.emit()

    def _load(self) -> dict[str, float]:
        figi_to_key = {figi: key for key, figi in self.key_and_figi}
        figis = [figi for _, figi in self.key_and_figi]
        out: dict[str, float] = {}

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
                out[key] = units + nano / 1e9

        return out


class QuotesHub(QtCore.QObject):
    quotes_updated = QtCore.pyqtSignal(object)  # dict[str, float], key = InstrumentInfo.fav_key()
    error = QtCore.pyqtSignal(str)

    def __init__(self, token: str, instruments_controller: InstrumentsController, parent=None):
        super().__init__(parent)
        self.token = token
        self.instruments_controller = instruments_controller
        self._prices: dict[str, float] = {}
        self._thread: Optional[QtCore.QThread] = None
        self._worker = None
        self._refresh_seq = 0

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.request_refresh)

        self.instruments_controller.favorites_updated.connect(lambda *_: self.request_refresh())

    def start(self):
        self._dbg("start")
        self._timer.start()
        self.request_refresh()

    def stop(self):
        self._dbg("stop")
        self._timer.stop()

    def _dbg(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[quotes-hub:{ts}] {msg}")

    def request_refresh(self):
        if self._thread and self._thread.isRunning():
            self._dbg("skip refresh: previous worker still running")
            return

        payload: list[tuple[str, str]] = []
        for info in self.instruments_controller.favorites():
            figi = (info.figi or info.instrument_id or "").strip()
            if figi:
                payload.append((info.fav_key(), figi))

        if not payload:
            self._dbg("skip refresh: favorites payload is empty")
            return

        self._refresh_seq += 1
        self._dbg(f"refresh #{self._refresh_seq} payload={len(payload)}")

        self._thread = QtCore.QThread(self)
        self._worker = _QuotesLoader(self.token, payload)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.error.connect(self.error.emit)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_finished)

        self._thread.start()

    def _on_loaded(self, prices: dict[str, float]):
        if not prices:
            self._dbg("loaded: no prices returned")
            return
        self._prices.update(prices)
        self._dbg(f"loaded: prices={len(prices)} cached={len(self._prices)}")
        self.quotes_updated.emit(dict(self._prices))

    def _on_finished(self):
        self._dbg("worker references cleared")
        self._worker = None
        self._thread = None

    def get_price(self, info: InstrumentInfo) -> Optional[float]:
        return self._prices.get(info.fav_key())

    def get_price_text(self, info: InstrumentInfo) -> str:
        p = self.get_price(info)
        if p is None:
            return ""
        return f"{p:.6f}".rstrip("0").rstrip(".")