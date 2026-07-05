from __future__ import annotations

from typing import Any, Optional

from PyQt6 import QtCore, QtWidgets
from t_tech.invest import Client

from app.config import TOKEN
from core.instruments_catalog import InstrumentInfo
from tabs.instruments_controller import InstrumentsController
from tabs.quotes_hub import QuotesHub


class _FavoritesPositionsLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # dict[str, float], key=figi
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

    def __init__(
        self,
        controller: InstrumentsController,
        quotes_hub: QuotesHub,
        trading_context: Any = None,
        parent=None,
    ):
        super().__init__(parent)
        self.controller = controller
        self.quotes_hub = quotes_hub
        self.trading_context = trading_context if trading_context is not None else getattr(parent, "trading_context", None)

        self._selected: Optional[InstrumentInfo] = None
        self._price_by_key: dict[str, str] = {}
        self._qty_by_figi: dict[str, float] = {}
        self._account_id = str(getattr(self.trading_context, "account_id", "") or "")
        self._qty_thread: Optional[QtCore.QThread] = None
        self._qty_worker = None

        self.lbl = QtWidgets.QLabel("Избранное")
        self.btn_refresh_prices = QtWidgets.QPushButton("Обновить цены")
        self.btn_refresh_qty = QtWidgets.QPushButton("Обновить количество")

        self.tbl_fav = QtWidgets.QTableWidget(0, 5)
        self.tbl_fav.setHorizontalHeaderLabels(["Type", "Инструмент", "ISIN", "Цена", "Количество"])
        self.tbl_fav.horizontalHeader().setStretchLastSection(True)
        self.tbl_fav.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_fav.setWordWrap(True)
        self.tbl_fav.verticalHeader().setDefaultSectionSize(44)
        self.tbl_fav.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_fav.setColumnHidden(0, True)
        self.tbl_fav.setColumnHidden(2, True)
        self.tbl_fav.setColumnWidth(1, 250)
        self.tbl_fav.setColumnWidth(3, 100)
        self.tbl_fav.setColumnWidth(4, 120)

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

        if self.trading_context is not None and hasattr(self.trading_context, "account_changed"):
            self.trading_context.account_changed.connect(self._on_account_changed)

        self.controller.emit_initial_state()
        QtCore.QTimer.singleShot(0, self.refresh_quantities)

    def _on_account_changed(self, account_id: str):
        self._account_id = str(account_id or "")
        self.refresh_quantities()

    def refresh_quantities(self):
        if self._qty_thread is not None and self._qty_thread.isRunning():
            return

        if not self._account_id:
            self._qty_by_figi = {}
            self._on_favorites_updated(self.controller.favorites())
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
        self._qty_thread.finished.connect(self._cleanup_qty_worker)

        self._qty_thread.start()

    def _cleanup_qty_worker(self):
        self._qty_worker = None
        self._qty_thread = None

    def _on_quantities_loaded(self, qty_by_figi: dict[str, float]):
        self._qty_by_figi = qty_by_figi or {}
        self._on_favorites_updated(self.controller.favorites())

    def _on_quantities_error(self, tb: str):
        print("===== ERROR (_FavoritesOnlyPicker qty) =====")
        print(tb)
        print("============================================")

    def _qty_for(self, info: InstrumentInfo) -> float:
        figi = (info.figi or info.instrument_id or "").strip()
        if not figi:
            return 0.0
        return float(self._qty_by_figi.get(figi, 0.0) or 0.0)

    def _qty_text(self, info: InstrumentInfo) -> str:
        q = self._qty_for(info)
        if abs(q) < 1e-12:
            return "0"
        return f"{q:.6f}".rstrip("0").rstrip(".")

    def _on_favorites_updated(self, favs: list[InstrumentInfo]):
        self.tbl_fav.setRowCount(0)
        self.tbl_fav.setSortingEnabled(False)

        for info in favs:
            r = self.tbl_fav.rowCount()
            self.tbl_fav.insertRow(r)

            key = info.fav_key()
            price = self._price_by_key.get(key, "-")
            qty = self._qty_text(info)

            kind_letter = "S" if info.kind == "share" else ("E" if info.kind == "etf" else ("B" if info.kind == "bond" else "?"))
            type_item = QtWidgets.QTableWidgetItem(kind_letter)
            instrument_item = QtWidgets.QTableWidgetItem(f"{info.ticker} | {info.name}")
            isin_item = QtWidgets.QTableWidgetItem(info.isin)
            price_item = QtWidgets.QTableWidgetItem(str(price))
            qty_item = QtWidgets.QTableWidgetItem(str(qty))

            instrument_item.setData(QtCore.Qt.ItemDataRole.UserRole, info)

            self.tbl_fav.setItem(r, 0, type_item)
            self.tbl_fav.setItem(r, 1, instrument_item)
            self.tbl_fav.setItem(r, 2, isin_item)
            self.tbl_fav.setItem(r, 3, price_item)
            self.tbl_fav.setItem(r, 4, qty_item)

        self.tbl_fav.setSortingEnabled(True)

    def _on_quotes_updated(self, prices: dict):
        self._price_by_key = {}
        for info in self.controller.favorites():
            p = prices.get(info.fav_key())
            if p is not None:
                self._price_by_key[info.fav_key()] = f"{float(p):.6f}".rstrip("0").rstrip(".")
        self._on_favorites_updated(self.controller.favorites())

    def _emit_selected(self, *_):
        sel = self.tbl_fav.selectionModel().selectedRows()
        if not sel:
            return
        row = sel[0].row()
        item = self.tbl_fav.item(row, 1)
        if item is None:
            return
        info = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not info:
            return
        self._selected = info
        self.instrument_selected.emit(info)

    def get_price_for(self, info: InstrumentInfo) -> str:
        return self._price_by_key.get(info.fav_key(), "")
