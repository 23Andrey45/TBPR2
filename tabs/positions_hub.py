from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from PyQt6 import QtCore
from t_tech.invest import Client

from core.instruments_catalog import InstrumentInfo


class _PositionsWorker(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # dict: {"seq": int, "by_figi": dict[str, float]}
    error = QtCore.pyqtSignal(str)

    def __init__(self, token: str):
        super().__init__()
        self.token = token
        self._stopping = False

    @QtCore.pyqtSlot()
    def stop(self):
        self._stopping = True

    @QtCore.pyqtSlot(int, str)
    def fetch(self, seq: int, account_id: str):
        if self._stopping:
            return
        if not account_id:
            self.loaded.emit({"seq": seq, "by_figi": {}})
            return

        try:
            by_figi = self._load_positions(account_id)
            self.loaded.emit({"seq": seq, "by_figi": by_figi})
        except Exception as exc:
            import traceback

            self.error.emit(f"{exc}\n{traceback.format_exc()}")

    def _load_positions(self, account_id: str) -> dict[str, float]:
        out: dict[str, float] = {}

        # Preferred path: reuse project API wrapper (same behavior as old picker loader).
        try:
            from core.sandbox_trading_api import get_sandbox_portfolio

            rows = get_sandbox_portfolio(self.token, account_id)
            for row in rows:
                figi = str(getattr(row, "figi", "") or "").strip()
                qty = float(getattr(row, "quantity", 0.0) or 0.0)
                if figi:
                    out[figi] = qty
            return out
        except Exception:
            pass

        with Client(token=self.token) as client:
            sb = getattr(client, "sandbox", None)
            if sb is None:
                return out

            method = getattr(sb, "get_sandbox_portfolio", None)
            if method is None:
                return out

            try:
                resp = method(account_id=account_id)
            except TypeError:
                return out

            positions = list(getattr(resp, "positions", []) or [])
            for pos in positions:
                figi = str(getattr(pos, "figi", "") or "").strip()
                qty = float(getattr(pos, "quantity", 0.0) or 0.0)
                if figi:
                    out[figi] = qty

        return out


class PositionsHub(QtCore.QObject):
    positions_updated = QtCore.pyqtSignal(object)  # dict[str, float], key=fav_key
    error = QtCore.pyqtSignal(str)

    _request_fetch = QtCore.pyqtSignal(int, str)

    def __init__(self, token: str, instruments_controller, trading_context, parent=None):
        super().__init__(parent)
        self.token = token
        self.instruments_controller = instruments_controller
        self.trading_context = trading_context

        self._positions: dict[str, float] = {}
        self._positions_by_figi: dict[str, float] = {}
        self._seq = 0
        self._in_flight = False

        self._thread = QtCore.QThread(self)
        self._worker = _PositionsWorker(self.token)
        self._worker.moveToThread(self._thread)
        self._thread.start()

        self._request_fetch.connect(self._worker.fetch)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.request_refresh)

        self.trading_context.account_changed.connect(lambda *_: self.request_refresh())
        self.instruments_controller.favorites_updated.connect(lambda *_: self._rebuild_key_cache())

    def start(self):
        self._dbg("start")
        self._timer.start()
        self.request_refresh()

    def stop(self, wait_ms: int = 2000):
        self._dbg("stop")
        self._timer.stop()
        self._in_flight = False
        try:
            QtCore.QMetaObject.invokeMethod(self._worker, "stop", QtCore.Qt.ConnectionType.QueuedConnection)
        except Exception:
            pass
        self._thread.quit()
        self._thread.wait(wait_ms)

    def request_refresh(self):
        if self._in_flight:
            return
        account_id = getattr(self.trading_context, "account_id", "") or ""
        self._seq += 1
        self._in_flight = True
        self._request_fetch.emit(self._seq, account_id)

    def _rebuild_key_cache(self):
        for info in self.instruments_controller.favorites():
            figi = (info.figi or info.instrument_id or "").strip()
            if not figi:
                continue
            qty = self._positions_by_figi.get(figi)
            if qty is not None:
                self._positions[info.fav_key()] = qty
        self.positions_updated.emit(dict(self._positions))

    @QtCore.pyqtSlot(object)
    def _on_loaded(self, payload: dict):
        seq = int(payload.get("seq", 0) or 0)
        if seq != self._seq:
            return
        self._in_flight = False

        by_figi = payload.get("by_figi", {}) or {}
        self._positions_by_figi = dict(by_figi)

        self._positions.clear()
        self._rebuild_key_cache()
        self._dbg(f"loaded by_figi={len(by_figi)} keyed={len(self._positions)}")

    @QtCore.pyqtSlot(str)
    def _on_error(self, err: str):
        self._in_flight = False
        self.error.emit(err)

    def get_qty(self, info: InstrumentInfo) -> float:
        q = self._positions.get(info.fav_key())
        if q is not None:
            return float(q)
        figi = (info.figi or info.instrument_id or "").strip()
        if figi:
            q = self._positions_by_figi.get(figi)
            if q is not None:
                return float(q)
        return 0.0

    def get_qty_text(self, info: InstrumentInfo) -> str:
        q = self.get_qty(info)
        if abs(q) < 1e-12:
            return "0"
        return f"{q:.6f}".rstrip("0").rstrip(".")

    def _dbg(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[positions-hub:{ts}] {msg}")
