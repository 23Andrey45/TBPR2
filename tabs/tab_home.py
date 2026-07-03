# tabs\tab_home.py
from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtWidgets

from app.config import CANDLES_DIR
from core.instruments_catalog import InstrumentInfo
from core.candle_cache import candles_cache_path

from tabs.home_controller import HomeController
from tabs.instruments_controller import InstrumentsController
from tabs.instrument_picker_widget import InstrumentPickerWidget, kind_to_short
from tabs.candles_panel_widget import CandlesPanelWidget


class HomeTab(QtWidgets.QWidget):
    def __init__(self, instruments_controller: InstrumentsController, parent=None):
        super().__init__(parent)

        self.instr_controller = instruments_controller
        self.candles_controller = HomeController(token=self.instr_controller.token, parent=self)

        self._selected: Optional[InstrumentInfo] = None
        self._last_source: str = ""  # internet|file|cache

        # ---- picker (слева)
        self.picker = InstrumentPickerWidget(controller=self.instr_controller, parent=self)
        self.picker.instrument_selected.connect(self._on_instrument_selected)

        # ---- candles panel (справа)
        self.panel = CandlesPanelWidget(parent=self)

        # связать “пересчитать стратегию”
        self.panel.strategies_widget.recalc_requested.connect(self.candles_controller.recalc_one)

        # layout
        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        main_splitter.addWidget(self.picker)
        main_splitter.addWidget(self.panel)
        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 6)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(main_splitter)

        # ---- panel actions -> controller
        self.panel.download_clicked.connect(self._on_download_clicked)
        self.panel.stop_clicked.connect(self.candles_controller.stop)
        self.panel.load_csv_requested.connect(self._on_load_csv)
        self.panel.save_csv_requested.connect(self.candles_controller.save_to_csv)

        # ---- controller -> panel
        self.candles_controller.status_changed.connect(self.panel.set_status_text)
        self.candles_controller.loading_changed.connect(self.panel.set_loading)
        self.candles_controller.candle_received.connect(self.panel.append_candle)

        self.candles_controller.dividends_ready.connect(self._on_dividends_ready)
        self.candles_controller.strategies_ready.connect(self.panel.strategies_widget.set_results)
        self.candles_controller.strategy_updated.connect(self.panel.strategies_widget.update_one)

        self.candles_controller.error.connect(self._print_error)

    def stop_loading(self):
        self.candles_controller.stop()

    # -------- instrument selection --------

    def _on_instrument_selected(self, info: InstrumentInfo):
        self._selected = info
        self.candles_controller.set_instrument(info)

        self.panel.set_instrument_text(
            f"Инструмент: {kind_to_short(info.kind)} | {info.ticker} | {info.name} | {info.isin}"
        )

        # Автоподгрузка кэша только для избранного
        if not self.instr_controller.is_favorite(info):
            return

        cache_file = candles_cache_path(CANDLES_DIR, info, self.candles_controller.interval, self.candles_controller.days)
        if cache_file.exists():
            self._last_source = "cache"
            self.panel.clear_candles()
            self.panel.set_status_text(f"Кэш: {cache_file.name}")
            self.candles_controller.load_from_csv(str(cache_file))
        else:
            self.panel.set_status_text(f"Кэш не найден: {cache_file.name}")

    # -------- actions --------

    def _require_selected(self) -> bool:
        if self._selected is None:
            self.panel.set_status_text("Сначала выбери инструмент (двойной клик)")
            return False
        return True

    def _on_download_clicked(self):
        if not self._require_selected():
            return
        self._last_source = "internet"
        self.panel.clear_candles()
        self.candles_controller.start_download(self._selected.instrument_id)

    def _on_load_csv(self, path: str):
        self._last_source = "file"
        self.panel.clear_candles()
        self.candles_controller.load_from_csv(path)

    # -------- dividends display --------

    def _on_dividends_ready(self, payload: dict):
        divs = payload.get("dividends", []) or []
        rs = payload.get("range_start")
        re = payload.get("range_end")
        self.panel.set_dividends(divs, rs, re)

    # -------- misc --------

    def _print_error(self, tb: str):
        print("===== ERROR (HomeTab) =====")
        print(tb)
        print("===========================")
