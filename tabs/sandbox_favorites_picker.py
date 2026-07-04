from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6 import QtCore, QtWidgets
from t_tech.invest import Client

from app.config import FAVORITES_FILE, TOKEN
from core.instruments_catalog import InstrumentInfo
from tabs.instruments_controller import InstrumentsController
from tabs.quotes_hub import QuotesHub


class FavoritesOnlyPicker(QtWidgets.QWidget):
    instrument_selected = QtCore.pyqtSignal(object)

    def __init__(self, controller: InstrumentsController, quotes_hub: QuotesHub, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.quotes_hub = quotes_hub
        self._selected: Optional[InstrumentInfo] = None
        self._qty_by_key: dict[str, int] = self._load_quantities()
        self._price_by_key: dict[str, str] = {}

        self.lbl = QtWidgets.QLabel("Избранное")
        self.btn_refresh_prices = QtWidgets.QPushButton("Обновить")
        self.btn_save_qty = QtWidgets.QPushButton("Сохранить")

        self.tbl_fav = QtWidgets.QTableWidget(0, 5)
        self.tbl_fav.setHorizontalHeaderLabels(["Type", "Инструмент", "ISIN", "Цена", "Количество"])
        self.tbl_fav.horizontalHeader().setStretchLastSection(True)
        self.tbl_fav.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_fav.setWordWrap(True)
        self.tbl_fav.verticalHeader().setDefaultSectionSize(44)
        self.tbl_fav.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.tbl_fav.setColumnHidden(0, True)
        self.tbl_fav.setColumnHidden(2, True)
        self.tbl_fav.setColumnWidth(1, 250)
        self.tbl_fav.setColumnWidth(3, 100)
        self.tbl_fav.setColumnWidth(4, 90)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.lbl)
        top.addStretch()
        top.addWidget(self.btn_refresh_prices)
        top.addWidget(self.btn_save_qty)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tbl_fav)

        self.controller.favorites_updated.connect(self._on_favorites_updated)
        self.tbl_fav.cellDoubleClicked.connect(self._emit_selected)
        self.btn_refresh_prices.clicked.connect(self.quotes_hub.request_refresh)
        self.btn_save_qty.clicked.connect(self._save_quantities)
        self.quotes_hub.quotes_updated.connect(self._on_quotes_updated)
        self.controller.emit_initial_state()

    def _on_favorites_updated(self, favs: list[InstrumentInfo]):
        self.tbl_fav.setRowCount(0)
        self.tbl_fav.setSortingEnabled(False)

        for info in favs:
            r = self.tbl_fav.rowCount()
            self.tbl_fav.insertRow(r)

            key = info.fav_key()
            qty = self._qty_by_key.get(key, 0)
            price = self._price_by_key.get(key, "-")

            kind_letter = "S" if info.kind == "share" else ("E" if info.kind == "etf" else ("B" if info.kind == "bond" else "?"))
            type_item = QtWidgets.QTableWidgetItem(kind_letter)
            instrument_item = QtWidgets.QTableWidgetItem(f"{info.name}\n{kind_letter} | {info.ticker} | {info.isin}")
            isin_item = QtWidgets.QTableWidgetItem(info.isin)
            price_item = QtWidgets.QTableWidgetItem(price)
            qty_item = QtWidgets.QTableWidgetItem(str(qty))

            for item in (type_item, instrument_item, isin_item, price_item):
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)

            self.tbl_fav.setItem(r, 0, type_item)
            self.tbl_fav.setItem(r, 1, instrument_item)
            self.tbl_fav.setItem(r, 2, isin_item)
            self.tbl_fav.setItem(r, 3, price_item)
            self.tbl_fav.setItem(r, 4, qty_item)

            item = self.tbl_fav.item(r, 0)
            if item is not None:
                item.setData(QtCore.Qt.ItemDataRole.UserRole, info)

        self.tbl_fav.setSortingEnabled(True)
        self.tbl_fav.resizeRowsToContents()

    def get_price_for(self, info: InstrumentInfo) -> str:
        key = info.fav_key()
        cached = self._price_by_key.get(key, "")
        if cached and cached != "-":
            return cached
        self.quotes_hub.request_refresh()
        return ""

    def _on_quotes_updated(self, prices_by_key: dict[str, float]):
        changed = False
        for key, value in prices_by_key.items():
            text = f"{float(value):.6f}".rstrip("0").rstrip(".")
            if self._price_by_key.get(key) != text:
                self._price_by_key[key] = text
                changed = True
        if changed:
            self._on_favorites_updated(self.controller.favorites())

    def _load_quantities(self) -> dict[str, int]:
        path = Path(FAVORITES_FILE)
        if not path.exists():
            return {}

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        out: dict[str, int] = {}
        for item in payload.get("items", []) or []:
            info = InstrumentInfo.from_dict(item)
            key = info.fav_key()
            try:
                qty = int(item.get("qty", 0) or 0)
            except Exception:
                qty = 0
            out[key] = max(0, qty)
        return out

    def _collect_quantities_from_table(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in range(self.tbl_fav.rowCount()):
            info_item = self.tbl_fav.item(row, 0)
            qty_item = self.tbl_fav.item(row, 4)
            if info_item is None:
                continue
            info = info_item.data(QtCore.Qt.ItemDataRole.UserRole)
            if info is None:
                continue

            raw = qty_item.text().strip() if qty_item is not None else "0"
            try:
                qty = int(raw)
            except Exception:
                qty = 0
            out[info.fav_key()] = max(0, qty)
        return out

    def _save_quantities(self):
        self._qty_by_key = self._collect_quantities_from_table()

        items = []
        for info in self.controller.favorites():
            data = info.to_dict()
            data["qty"] = self._qty_by_key.get(info.fav_key(), 0)
            items.append(data)

        path = Path(FAVORITES_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.lbl.setText("Избранное (количества сохранены)")

    def _refresh_prices(self):
        if self._price_thread and self._price_thread.isRunning():
            return

        payload: list[tuple[str, str]] = []
        for info in self.controller.favorites():
            figi = (info.figi or info.instrument_id or "").strip()
            if figi:
                payload.append((info.fav_key(), figi))

        if not payload:
            self.lbl.setText("Избранное (нет FIGI для обновления цен)")
            return

        self.lbl.setText("Избранное (обновляю цены...)")

        self._price_thread = QtCore.QThread(self)
        self._price_worker = _FavoritesPricesLoader(TOKEN, payload)
        self._price_worker.moveToThread(self._price_thread)

        self._price_thread.started.connect(self._price_worker.run)
        self._price_worker.loaded.connect(self._on_prices_loaded)
        self._price_worker.error.connect(self._on_prices_error)
        self._price_worker.finished.connect(self._price_thread.quit)
        self._price_worker.finished.connect(self._price_worker.deleteLater)
        self._price_thread.finished.connect(self._price_thread.deleteLater)
        self._price_thread.finished.connect(self._cleanup_price_worker)

        self._price_thread.start()

    def _on_prices_loaded(self, prices_by_key: dict[str, str]):
        self._price_by_key = prices_by_key or {}
        self.lbl.setText("Избранное (цены обновлены)")
        self._on_favorites_updated(self.controller.favorites())

    def _on_prices_error(self, tb: str):
        self.lbl.setText("Избранное (ошибка обновления цен, см. консоль)")
        print("===== ERROR (_FavoritesOnlyPicker prices) =====")
        print(tb)
        print("===============================================")

    def _cleanup_price_worker(self):
        self._price_worker = None
        self._price_thread = None

    def _fetch_single_price(self, figi: str) -> str:
        try:
            with Client(token=TOKEN) as client:
                resp = client.market_data.get_last_prices(figi=[figi])
                prices = list(getattr(resp, "last_prices", []) or [])
                if not prices:
                    return ""

                p = getattr(prices[0], "price", None)
                if p is None:
                    return ""

                units = int(getattr(p, "units", 0) or 0)
                nano = int(getattr(p, "nano", 0) or 0)
                val = units + nano / 1e9
                return f"{val:.6f}".rstrip("0").rstrip(".")
        except Exception:
            return ""

    def _emit_selected(self, *_):
        sel = self.tbl_fav.selectionModel().selectedRows()
        if not sel:
            return
        row = sel[0].row()
        item = self.tbl_fav.item(row, 0)
        if item is None:
            return
        info = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if info is not None:
            self._selected = info
            self.instrument_selected.emit(info)

    def selected_instrument(self) -> Optional[InstrumentInfo]:
        return self._selected


class _FavoritesPricesLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, keys_and_figi: list[tuple[str, str]]):
        super().__init__()
        self.token = token
        self.keys_and_figi = keys_and_figi

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.loaded.emit(self._load_prices())
        except Exception:
            import traceback

            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()

    def _load_prices(self) -> dict[str, str]:
        figis = [figi for _, figi in self.keys_and_figi]
        figi_to_key = {figi: key for key, figi in self.keys_and_figi}
        out: dict[str, str] = {}

        with Client(token=self.token) as client:
            resp = client.market_data.get_last_prices(figi=figis)
            for lp in getattr(resp, "last_prices", []) or []:
                figi = str(getattr(lp, "figi", "") or "")
                key = figi_to_key.get(figi)
                if not key:
                    continue

                p = getattr(lp, "price", None)
                if p is None:
                    out[key] = "-"
                    continue

                units = int(getattr(p, "units", 0) or 0)
                nano = int(getattr(p, "nano", 0) or 0)
                val = units + nano / 1e9
                out[key] = f"{val:.6f}".rstrip("0").rstrip(".")

        for key, _ in self.keys_and_figi:
            out.setdefault(key, "-")

        return out