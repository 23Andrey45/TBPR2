# tabs/home_controller.py
from __future__ import annotations

import traceback
from datetime import timedelta
from typing import Optional, Any

from PyQt6 import QtCore
from t_tech.invest import CandleInterval

from core.candle_storage import load_candles_csv, save_candles_csv
from core.trading_logic import CandleData, now_utc
from core.instruments_catalog import InstrumentInfo
from core.backtest_runner import BacktestRunner
from core.strategies import STRATEGIES
from core.strategies.base import StrategyResult, StrategyContext

from tabs.workers import CandleLoader, DividendsLoader


class HomeController(QtCore.QObject):
    status_changed = QtCore.pyqtSignal(str)
    loading_changed = QtCore.pyqtSignal(bool)

    candle_received = QtCore.pyqtSignal(object)       # CandleData
    dividends_ready = QtCore.pyqtSignal(object)       # dict: {"dividends": [...], "range_start": dt|None, "range_end": dt|None}
    strategies_ready = QtCore.pyqtSignal(object)      # dict[str, StrategyResult]
    strategy_updated = QtCore.pyqtSignal(object)      # StrategyResult

    error = QtCore.pyqtSignal(str)                    # traceback

    def __init__(self, token: str, parent=None):
        super().__init__(parent)
        self.token = token

        self.days = 365
        self.interval = CandleInterval.CANDLE_INTERVAL_HOUR

        self._candles: list[CandleData] = []

        self._thread: Optional[QtCore.QThread] = None
        self._worker: Optional[CandleLoader] = None

        self._div_thread: Optional[QtCore.QThread] = None
        self._div_worker: Optional[DividendsLoader] = None
        self._dividends = []

        self._instrument: Optional[InstrumentInfo] = None

        self._runner = BacktestRunner(STRATEGIES)
        self._params_by_strategy: dict[str, dict[str, Any]] = {}
        self._results: dict[str, StrategyResult] = {}

    # ---- instrument ----
    def set_instrument(self, info: InstrumentInfo | None):
        self._instrument = info

    @property
    def candles(self) -> list[CandleData]:
        return self._candles

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.isRunning())

    # ------------------- internet -------------------

    def start_download(self, instrument_id: str):
        if self.is_running():
            return

        self._candles.clear()
        self._dividends = []
        self._emit_dividends([])

        self.loading_changed.emit(True)
        self.status_changed.emit(f"Загрузка свечей...")

        from_ = now_utc() - timedelta(days=self.days)

        self._thread = QtCore.QThread(self)
        self._worker = CandleLoader(
            token=self.token,
            instrument_id=instrument_id,
            from_=from_,
            interval=self.interval,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.candle_received.connect(self._on_candle_from_worker)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._on_worker_finished)

        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def stop(self):
        if self._worker:
            self._worker.stop()
            self.status_changed.emit("Остановка...")

    @QtCore.pyqtSlot(object)
    def _on_candle_from_worker(self, c: CandleData):
        self._candles.append(c)
        self.candle_received.emit(c)

    @QtCore.pyqtSlot(str)
    def _on_worker_error(self, tb: str):
        self.error.emit(tb)

    @QtCore.pyqtSlot()
    def _on_worker_finished(self):
        self.loading_changed.emit(False)

        if not self._candles:
            self.status_changed.emit("Свечи не получены")
            self._cleanup_candle_worker()
            return

        self._load_dividends_then_calc()
        self._cleanup_candle_worker()

    # ------------------- CSV -------------------

    def load_from_csv(self, path: str):
        if self.is_running():
            return

        self.loading_changed.emit(True)
        self.status_changed.emit("Чтение CSV...")

        try:
            self._candles = load_candles_csv(path)
            self._dividends = []
            self._emit_dividends([])

            for c in self._candles:
                self.candle_received.emit(c)

            if not self._candles:
                self.status_changed.emit("CSV пустой")
                return

            self._load_dividends_then_calc()

        except Exception:
            self.error.emit(traceback.format_exc())
            self.status_changed.emit("Ошибка чтения CSV")

        finally:
            self.loading_changed.emit(False)

    def save_to_csv(self, path: str):
        if not self._candles:
            self.status_changed.emit("Нечего сохранять (сначала загрузите свечи)")
            return
        try:
            save_candles_csv(path, self._candles)
            self.status_changed.emit(f"Сохранено: {path}")
        except Exception:
            self.error.emit(traceback.format_exc())
            self.status_changed.emit("Ошибка сохранения CSV")

    # ------------------- strategies API for UI -------------------

    def recalc_one(self, strategy_id: str, user_params: dict[str, Any]):
        if not self._candles:
            self.status_changed.emit("Нет свечей для пересчёта")
            return

        try:
            self._params_by_strategy[strategy_id] = dict(user_params)
            ctx = StrategyContext(instrument=self._instrument, dividends=self._dividends)
            result = self._runner.run_one(self._candles, strategy_id=strategy_id, user_params=user_params, context=ctx)
            self._results[strategy_id] = result
            self.strategy_updated.emit(result)
            self.status_changed.emit("Готово")
        except Exception:
            self.error.emit(traceback.format_exc())
            self.status_changed.emit("Ошибка пересчёта стратегии")

    # ------------------- dividends + calc -------------------

    def _emit_dividends(self, divs: list):
        start = self._candles[0].time if self._candles and hasattr(self._candles[0].time, "tzinfo") else None
        end = self._candles[-1].time if self._candles and hasattr(self._candles[-1].time, "tzinfo") else None
        self.dividends_ready.emit({"dividends": divs, "range_start": start, "range_end": end})

    def _load_dividends_then_calc(self):
        inst = self._instrument
        if inst is None:
            self._dividends = []
            self._emit_dividends([])
            self._recalc_all_strategies()
            return

        kind = (inst.kind or "").lower()
        if kind not in ("share", "etf") or not inst.figi:
            self._dividends = []
            self._emit_dividends([])
            self._recalc_all_strategies()
            return

        if not self._candles or not hasattr(self._candles[0].time, "tzinfo"):
            self._dividends = []
            self._emit_dividends([])
            self._recalc_all_strategies()
            return

        from_ = self._candles[0].time - timedelta(days=30)
        to = self._candles[-1].time + timedelta(days=30)

        if self._div_thread and self._div_thread.isRunning():
            return

        self.status_changed.emit("Загружаю дивиденды...")

        self._div_thread = QtCore.QThread(self)
        self._div_worker = DividendsLoader(self.token, inst.figi, from_, to)
        self._div_worker.moveToThread(self._div_thread)

        self._div_thread.started.connect(self._div_worker.run)
        self._div_worker.loaded.connect(self._on_dividends_loaded)
        self._div_worker.error.connect(self.error.emit)

        self._div_worker.finished.connect(self._div_thread.quit)
        self._div_worker.finished.connect(self._div_worker.deleteLater)
        self._div_thread.finished.connect(self._div_thread.deleteLater)
        self._div_thread.finished.connect(self._cleanup_div_worker)

        self._div_thread.start()

    def _on_dividends_loaded(self, divs: list):
        self._dividends = divs or []
        self._emit_dividends(self._dividends)
        self._recalc_all_strategies()

    def _cleanup_div_worker(self):
        self._div_worker = None
        self._div_thread = None

    def _recalc_all_strategies(self):
        try:
            self.status_changed.emit("Считаю стратегии...")
            ctx = StrategyContext(instrument=self._instrument, dividends=self._dividends)
            self._results = self._runner.run_all(self._candles, params_by_strategy=self._params_by_strategy, context=ctx)
            self.strategies_ready.emit(self._results)
            self.status_changed.emit("Готово")
        except Exception:
            self.error.emit(traceback.format_exc())
            self.status_changed.emit("Ошибка расчёта стратегий")

    def _cleanup_candle_worker(self):
        self._worker = None
        self._thread = None
        