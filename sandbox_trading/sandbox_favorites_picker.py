# sandbox_trading/sandbox_favorites_picker.py
"""
Виджет выбора инструментов из избранного для песочницы.
Использует AppContext для обмена данными.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from PyQt6 import QtCore, QtWidgets
from t_tech.invest import Client

from app.config import TOKEN
from app.app_context import AppContext
from core.instruments_catalog import InstrumentInfo
from instruments.instruments_controller import InstrumentsController
from market_data.quotes_hub import QuotesHub


class _FavoritesPositionsLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str):
        super().__init__()
        self.token = token
        self.account_id = account_id

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.loaded.emit(self._load_positions())
        except Exception:
            import traceback
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()

    def _load_positions(self) -> dict[str, float]:
        out: dict[str, float] = {}
        try:
            from core.sandbox_trading_api import get_sandbox_portfolio
            rows = get_sandbox_portfolio(self.token, self.account_id)
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
                resp = method(account_id=self.account_id)
            except TypeError:
                return out
            positions = list(getattr(resp, "positions", []) or [])
            for pos in positions:
                figi = str(getattr(pos, "figi", "") or "").strip()
                qty = float(getattr(pos, "quantity", 0.0) or 0.0)
                if figi:
                    out[figi] = qty
        return out


class FavoritesOnlyPicker(QtWidgets.QWidget):
    instrument_selected = QtCore.pyqtSignal(object)
    _updating = False

    def __init__(
            self,
            controller: InstrumentsController,
            quotes_hub: QuotesHub,
            positions_hub: Any = None,
            app_context: AppContext = None,
            parent=None,
    ):
        super().__init__(parent)
        self.controller = controller
        self.quotes_hub = quotes_hub
        self.positions_hub = positions_hub
        self.app_context = app_context if app_context is not None else getattr(parent, "app_context", None)

        self._selected: Optional[InstrumentInfo] = None
        self._price_by_key: dict[str, str] = {}
        self._qty_by_figi: dict[str, float] = {}
        self._account_id = str(getattr(self.app_context, "sandbox_account_id", "") or "")
        self._qty_thread: Optional[QtCore.QThread] = None
        self._qty_worker = None
        self._render_scheduled = False
        self._last_render_time: Optional[datetime] = None
        self._update_count = 0

        self.lbl = QtWidgets.QLabel("Избранное")
        self.btn_refresh_prices = QtWidgets.QPushButton("Обновить цены")
        self.btn_refresh_qty = QtWidgets.QPushButton("Обновить количество")

        self.tbl_fav = QtWidgets.QTableWidget(0, 6)
        self.tbl_fav.setHorizontalHeaderLabels(["Type", "Инструмент", "ISIN", "Цена", "Статус", "Количество"])
        self.tbl_fav.horizontalHeader().setStretchLastSection(True)
        self.tbl_fav.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_fav.setWordWrap(True)
        self.tbl_fav.verticalHeader().setDefaultSectionSize(44)
        self.tbl_fav.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_fav.setColumnHidden(0, True)
        self.tbl_fav.setColumnHidden(2, True)
        self.tbl_fav.setColumnWidth(1, 250)
        self.tbl_fav.setColumnWidth(3, 100)
        self.tbl_fav.setColumnWidth(4, 100)
        self.tbl_fav.setColumnWidth(5, 120)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.lbl)
        top.addStretch()
        top.addWidget(self.btn_refresh_prices)
        top.addWidget(self.btn_refresh_qty)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tbl_fav)

        self.controller.favorites_updated.connect(self._on_favorites_updated)
        self.tbl_fav.cellDoubleClicked.connect(self._emit_selected)
        self.btn_refresh_prices.clicked.connect(self.quotes_hub.request_refresh)
        self.btn_refresh_qty.clicked.connect(self.refresh_quantities)
        self.quotes_hub.quotes_updated.connect(self._on_quotes_updated)
        self.quotes_hub.trading_status_updated.connect(self._on_trading_status_updated)

        self._status_update_timer = QtCore.QTimer(self)
        self._status_update_timer.setInterval(5000)
        self._status_update_timer.timeout.connect(self._update_status_display)
        self._status_update_timer.start()

        self._status_thread: Optional[QtCore.QThread] = None
        self._status_worker = None

        if self.positions_hub is not None and hasattr(self.positions_hub, "positions_updated"):
            self.positions_hub.positions_updated.connect(self._on_positions_updated)

        if self.app_context is not None and hasattr(self.app_context, "account_changed"):
            self.app_context.account_changed.connect(self._on_account_changed)

        self.controller.emit_initial_state()
        QtCore.QTimer.singleShot(0, self.refresh_quantities)

    def _on_account_changed(self, account_id: str):
        self._account_id = str(account_id or "")
        self.refresh_quantities()

    def refresh_quantities(self):
        if self._updating:
            return
        if self.positions_hub is not None:
            try:
                self.positions_hub.request_refresh()
            except Exception:
                pass
            return

        if self._qty_thread is not None and self._qty_thread.isRunning():
            return

        if not self._account_id:
            self._qty_by_figi = {}
            self._request_render()
            return

        self._qty_thread = QtCore.QThread(self)
        self._qty_worker = _FavoritesPositionsLoader(TOKEN, self._account_id)
        self._qty_worker.moveToThread(self._qty_thread)

        self._qty_thread.started.connect(self._qty_worker.run)
        self._qty_worker.loaded.connect(self._on_quantities_loaded)
        self._qty_worker.error.connect(self._on_quantities_error)
        self._qty_worker.finished.connect(self._qty_thread.quit)
        self._qty_worker.finished.connect(self._qty_worker.deleteLater)
        self._qty_thread.finished.connect(self._qty_thread.deleteLater)
        self._qty_thread.start()

    def _on_quantities_loaded(self, qty_by_figi: dict[str, float]):
        self._qty_by_figi = qty_by_figi
        self._request_render()

    def _on_quantities_error(self, tb: str):
        print(f"[FAV-PICKER] ERROR: {tb[:200]}...")

    def _on_favorites_updated(self, favs: list[InstrumentInfo]):
        self._request_render()

    def _on_quotes_updated(self, quotes: dict[str, float]):
        self._price_by_key = {k: f"{v:.6f}" for k, v in quotes.items()}
        self._request_render()

    def _on_positions_updated(self, positions: list):
        qty_by_figi = {}
        for pos in positions:
            figi = getattr(pos, "figi", "")
            qty = getattr(pos, "quantity", 0.0)
            if figi:
                qty_by_figi[figi] = float(qty or 0.0)
        self._qty_by_figi = qty_by_figi
        self._request_render()

    def _on_trading_status_updated(self, status: dict):
        self._request_render()

    def _update_status_display(self):
        self._request_render()

    def _emit_selected(self, row: int, column: int):
        item = self.tbl_fav.item(row, 0)
        if item is None:
            return
        info = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if info:
            self._selected = info
            self.instrument_selected.emit(info)

    def get_price_for(self, info: InstrumentInfo) -> Optional[str]:
        key = info.figi or info.isin or info.instrument_id
        return self._price_by_key.get(key)

    def _request_render(self):
        now = datetime.now()
        if self._last_render_time is not None:
            elapsed_ms = (now - self._last_render_time).total_seconds() * 1000
            if elapsed_ms < 100:
                if not self._render_scheduled:
                    self._render_scheduled = True
                    QtCore.QTimer.singleShot(100, self._request_render)
                return
        if self._render_scheduled:
            return
        self._render_scheduled = True
        self._last_render_time = now
        QtCore.QTimer.singleShot(0, self._render_table)

    def _render_table(self):
        self._render_scheduled = False
        self._update_count += 1
        favs = self.controller.favorites()
        self.tbl_fav.setRowCount(0)
        self.tbl_fav.setSortingEnabled(False)

        for info in favs:
            r = self.tbl_fav.rowCount()
            self.tbl_fav.insertRow(r)

            kind_item = QtWidgets.QTableWidgetItem(kind_to_short(info.kind))
            kind_item.setData(QtCore.Qt.ItemDataRole.UserRole, info)
            self.tbl_fav.setItem(r, 0, kind_item)

            name_widget = QtWidgets.QWidget()
            name_layout = QtWidgets.QVBoxLayout(name_widget)
            name_layout.setContentsMargins(4, 2, 4, 2)
            name_layout.setSpacing(0)
            ticker_label = QtWidgets.QLabel(info.ticker)
            ticker_label.setStyleSheet("font-weight: bold; color: #1976d2; font-size: 11px;")
            name_layout.addWidget(ticker_label)
            name_label = QtWidgets.QLabel(info.name or "-")
            name_label.setStyleSheet("color: #666; font-size: 10px;")
            name_layout.addWidget(name_label)
            self.tbl_fav.setCellWidget(r, 1, name_widget)

            self.tbl_fav.setItem(r, 2, QtWidgets.QTableWidgetItem(info.isin))

            key = info.figi or info.isin or info.instrument_id
            price_str = self._price_by_key.get(key, "-")
            self.tbl_fav.setItem(r, 3, QtWidgets.QTableWidgetItem(price_str))

            status = "-"
            self.tbl_fav.setItem(r, 4, QtWidgets.QTableWidgetItem(status))

            qty = self._qty_by_figi.get(info.figi, 0.0) if info.figi else 0.0
            qty_item = QtWidgets.QTableWidgetItem(f"{qty:,.6f}" if qty else "-")
            qty_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.tbl_fav.setItem(r, 5, qty_item)

        self.tbl_fav.setSortingEnabled(True)
        self.lbl.setText(f"Избранное ({len(favs)})")


def kind_to_short(kind: str) -> str:
    kind = (kind or "").lower()
    if kind == "share":
        return "SHARE"
    if kind == "bond":
        return "BOND"
    if kind == "etf":
        return "ETF"
    return kind.upper() or "?"