# tabs/candles_panel_widget.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PyQt6 import QtCore, QtWidgets

from core.trading_logic import CandleData
from core.dividends_api import DividendEvent
from tabs.strategy_results_widget import StrategyResultsWidget


class CandlesPanelWidget(QtWidgets.QWidget):
    download_clicked = QtCore.pyqtSignal()
    load_csv_requested = QtCore.pyqtSignal(str)
    save_csv_requested = QtCore.pyqtSignal(str)
    stop_clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._instrument_text = "Инструмент: не выбран"
        self._status_text = ""

        self.header = QtWidgets.QLabel(self._instrument_text)
        self.header.setWordWrap(True)

        # кнопки
        self.btn_download = QtWidgets.QPushButton("Свечи: из интернета")
        self.btn_load_csv = QtWidgets.QPushButton("Свечи: из CSV")
        self.btn_save_csv = QtWidgets.QPushButton("Свечи: сохранить CSV")
        self.btn_stop = QtWidgets.QPushButton("Остановить")
        self.btn_stop.setEnabled(False)

        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(self.btn_download)
        btns.addWidget(self.btn_load_csv)
        btns.addWidget(self.btn_save_csv)
        btns.addWidget(self.btn_stop)
        btns.addStretch()

        # вкладки данных
        self.data_tabs = QtWidgets.QTabWidget()

        self.candles_table = QtWidgets.QTableWidget(0, 6)
        self.candles_table.setHorizontalHeaderLabels(["time", "open", "high", "low", "close", "volume"])
        self.candles_table.horizontalHeader().setStretchLastSection(True)

        self.div_table = QtWidgets.QTableWidget(0, 7)
        self.div_table.setHorizontalHeaderLabels([
            "payment_date",
            "last_buy_date",
            "record_date",
            "div_net",
            "close_price",
            "yield",
            "counted",
        ])
        self.div_table.horizontalHeader().setStretchLastSection(True)
        self.div_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        self.data_tabs.addTab(self.candles_table, "Свечи")
        self.data_tabs.addTab(self.div_table, "Дивиденды")

        # стратегии (как было "под свечами")
        self.strategies_widget = StrategyResultsWidget()

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        splitter.addWidget(self.data_tabs)
        splitter.addWidget(self.strategies_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addLayout(btns)
        layout.addWidget(splitter)

        # wiring кнопок -> сигналы
        self.btn_download.clicked.connect(self.download_clicked.emit)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)

        self.btn_load_csv.clicked.connect(self._open_load_csv)
        self.btn_save_csv.clicked.connect(self._open_save_csv)

    # ---------- header ----------
    def set_instrument_text(self, text: str):
        self._instrument_text = text
        self._update_header()

    def set_status_text(self, text: str):
        self._status_text = text
        self._update_header()

    def _update_header(self):
        if self._status_text:
            self.header.setText(f"{self._instrument_text}    |    {self._status_text}")
        else:
            self.header.setText(self._instrument_text)

    # ---------- buttons state ----------
    def set_loading(self, is_loading: bool):
        self.btn_download.setEnabled(not is_loading)
        self.btn_load_csv.setEnabled(not is_loading)
        self.btn_save_csv.setEnabled(not is_loading)
        self.btn_stop.setEnabled(is_loading)

    # ---------- candles ----------
    def clear_candles(self):
        self.candles_table.setRowCount(0)

    def append_candle(self, c: CandleData):
        r = self.candles_table.rowCount()
        self.candles_table.insertRow(r)
        self.candles_table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(c.time)))
        self.candles_table.setItem(r, 1, QtWidgets.QTableWidgetItem(f"{c.open:.6f}"))
        self.candles_table.setItem(r, 2, QtWidgets.QTableWidgetItem(f"{c.high:.6f}"))
        self.candles_table.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{c.low:.6f}"))
        self.candles_table.setItem(r, 4, QtWidgets.QTableWidgetItem(f"{c.close:.6f}"))
        self.candles_table.setItem(r, 5, QtWidgets.QTableWidgetItem(str(c.volume)))

    # ---------- dividends ----------
    def set_dividends(self, dividends: list[DividendEvent], range_start: Optional[datetime], range_end: Optional[datetime]):
        self.div_table.setRowCount(0)
        for d in dividends:
            counted = ""
            if range_start is not None and range_end is not None:
                counted = "yes" if (range_start <= d.payment_date <= range_end) else "no"

            r = self.div_table.rowCount()
            self.div_table.insertRow(r)
            self.div_table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(d.payment_date)))
            self.div_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(d.last_buy_date)))
            self.div_table.setItem(r, 2, QtWidgets.QTableWidgetItem(str(d.record_date)))
            self.div_table.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{d.dividend_net_per_share:.6f} {d.currency}".strip()))
            self.div_table.setItem(r, 4, QtWidgets.QTableWidgetItem(f"{d.close_price:.6f}"))
            self.div_table.setItem(r, 5, QtWidgets.QTableWidgetItem(f"{d.yield_value:.6f}"))
            self.div_table.setItem(r, 6, QtWidgets.QTableWidgetItem(counted))

    # ---------- file dialogs ----------
    def _open_load_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Открыть CSV со свечами", "", "CSV files (*.csv);;All files (*.*)"
        )
        if path:
            self.load_csv_requested.emit(path)

    def _open_save_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Сохранить свечи в CSV", "candles.csv", "CSV files (*.csv);;All files (*.*)"
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        self.save_csv_requested.emit(path)
