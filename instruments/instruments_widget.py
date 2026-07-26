# tabs/instruments_widget.py
from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from core.instruments_catalog import InstrumentInfo
from tabs.instruments_controller import InstrumentsController


class InstrumentsWidget(QtWidgets.QWidget):
    instrument_selected = QtCore.pyqtSignal(object)  # InstrumentInfo

    def __init__(self, controller: InstrumentsController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._shares_cache: list[InstrumentInfo] = []
        self._bonds_cache: list[InstrumentInfo] = []
        self._etfs_cache: list[InstrumentInfo] = []

        self.btn_refresh = QtWidgets.QPushButton("Обновить")
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Поиск: тикер / название / ISIN")

        self.btn_add = QtWidgets.QPushButton("→ В избранное")
        self.btn_remove = QtWidgets.QPushButton("Удалить из избранного")

        self.lbl_status = QtWidgets.QLabel("")

        # Все акции
        self.tbl_all = QtWidgets.QTableWidget(0, 4)
        self.tbl_all.setHorizontalHeaderLabels(["Ticker", "Name", "ISIN", "★"])
        self.tbl_all.horizontalHeader().setStretchLastSection(True)
        self.tbl_all.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_all.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        # Избранные
        self.tbl_fav = QtWidgets.QTableWidget(0, 3)
        self.tbl_fav.setHorizontalHeaderLabels(["Ticker", "Name", "ISIN"])
        self.tbl_fav.horizontalHeader().setStretchLastSection(True)
        self.tbl_fav.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_fav.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        # Layout
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.btn_refresh)
        top.addWidget(self.search, 1)
        top.addWidget(self.lbl_status)

        mid = QtWidgets.QHBoxLayout()
        mid.addWidget(self.btn_add)
        mid.addWidget(self.btn_remove)
        mid.addStretch()

        tables = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        tables.addWidget(self.tbl_all)
        tables.addWidget(self.tbl_fav)
        tables.setStretchFactor(0, 3)
        tables.setStretchFactor(1, 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(mid)
        layout.addWidget(tables)

        # UI -> controller
        self.btn_refresh.clicked.connect(self.controller.refresh)
        self.btn_add.clicked.connect(self._add_selected_to_fav)
        self.btn_remove.clicked.connect(self._remove_selected_from_fav)
        self.search.textChanged.connect(self._apply_filter)

        # controller -> UI
        self.controller.status_changed.connect(self.lbl_status.setText)
        self.controller.shares_updated.connect(self._on_shares_updated)
        self.controller.bonds_updated.connect(self._on_bonds_updated)
        self.controller.etfs_updated.connect(self._on_etfs_updated)
        self.controller.favorites_updated.connect(self._on_fav_updated)
        self.controller.error.connect(self._print_error)
        self.controller.emit_initial_state()

        # выбор инструмента двойным кликом
        self.tbl_all.cellDoubleClicked.connect(lambda *_: self._emit_selected_from(self.tbl_all))
        self.tbl_fav.cellDoubleClicked.connect(lambda *_: self._emit_selected_from(self.tbl_fav))

    def _print_error(self, tb: str):
        print("===== ERROR (instruments) =====")
        print(tb)
        print("===============================")

    def _set_row_data(self, table: QtWidgets.QTableWidget, row: int, info: InstrumentInfo):
        # Сохраняем объект в UserRole первой ячейки
        item = table.item(row, 0)
        if item is None:
            item = QtWidgets.QTableWidgetItem()
            table.setItem(row, 0, item)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, info)

    def _get_selected_info(self, table: QtWidgets.QTableWidget) -> InstrumentInfo | None:
        sel = table.selectionModel().selectedRows()
        if not sel:
            return None
        r = sel[0].row()
        item = table.item(r, 0)
        if not item:
            return None
        info = item.data(QtCore.Qt.ItemDataRole.UserRole)
        return info

    def _emit_selected_from(self, table: QtWidgets.QTableWidget):
        info = self._get_selected_info(table)
        if info:
            self.instrument_selected.emit(info)

    def _on_shares_updated(self, items: list[InstrumentInfo]):
        self._shares_cache = items
        self._apply_filter()

    def _on_bonds_updated(self, items: list[InstrumentInfo]):
        self._bonds_cache = items
        self._apply_filter()

    def _on_etfs_updated(self, items: list[InstrumentInfo]):
        self._etfs_cache = items
        self._apply_filter()

    def _on_fav_updated(self, favs: list[InstrumentInfo]):
        self.tbl_fav.setRowCount(0)
        self.tbl_fav.setSortingEnabled(False)
        for info in favs:
            r = self.tbl_fav.rowCount()
            self.tbl_fav.insertRow(r)
            self.tbl_fav.setItem(r, 0, QtWidgets.QTableWidgetItem(info.ticker))
            self.tbl_fav.setItem(r, 1, QtWidgets.QTableWidgetItem(info.name))
            self.tbl_fav.setItem(r, 2, QtWidgets.QTableWidgetItem(info.isin))
            self._set_row_data(self.tbl_fav, r, info)
        self.tbl_fav.setSortingEnabled(True)

        # обновим звездочки в "All"
        self._apply_filter()

    def _apply_filter(self):
        q = self.search.text().strip().lower()

        def ok(info: InstrumentInfo) -> bool:
            if not q:
                return True
            return (
                q in (info.ticker or "").lower()
                or q in (info.name or "").lower()
                or q in (info.isin or "").lower()
            )

        all_items = self._shares_cache + self._bonds_cache + self._etfs_cache
        filtered = [x for x in all_items if ok(x)]

        self.tbl_all.setRowCount(0)
        self.tbl_all.setSortingEnabled(False)
        for info in filtered:
            r = self.tbl_all.rowCount()
            self.tbl_all.insertRow(r)

            self.tbl_all.setItem(r, 0, QtWidgets.QTableWidgetItem(info.ticker))
            self.tbl_all.setItem(r, 1, QtWidgets.QTableWidgetItem(info.name))
            self.tbl_all.setItem(r, 2, QtWidgets.QTableWidgetItem(info.isin))
            self.tbl_all.setItem(r, 3, QtWidgets.QTableWidgetItem("★" if self.controller.is_favorite(info) else ""))

            self._set_row_data(self.tbl_all, r, info)

        self.tbl_all.setSortingEnabled(True)

    def _add_selected_to_fav(self):
        info = self._get_selected_info(self.tbl_all)
        if info:
            self.controller.add_favorite(info)

    def _remove_selected_from_fav(self):
        info = self._get_selected_info(self.tbl_fav)
        if info:
            self.controller.remove_favorite(info)