# tabs\instrument_picker_widget.py
from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtWidgets

from core.instruments_catalog import InstrumentInfo
from tabs.instruments_controller import InstrumentsController


def kind_to_short(kind: str) -> str:
    kind = (kind or "").lower()
    if kind == "share":
        return "SHARE"
    if kind == "bond":
        return "BOND"
    if kind == "etf":
        return "ETF"
    return kind.upper() or "?"


class InstrumentPickerWidget(QtWidgets.QWidget):
    """
    1 строка: Обновить + Поиск
    2 строка: счетчики (Акции/Облигации/ETF) или статус загрузки
    3 зона: (таблица инструментов с вкладками) + (избранное)
    """

    instrument_selected = QtCore.pyqtSignal(object)  # InstrumentInfo

    def __init__(self, controller: InstrumentsController, parent=None):
        super().__init__(parent)
        self.controller = controller

        self._shares_cache: list[InstrumentInfo] = []
        self._bonds_cache: list[InstrumentInfo] = []
        self._etfs_cache: list[InstrumentInfo] = []

        self._selected: Optional[InstrumentInfo] = None

        # ---- row 1: refresh + search
        self.btn_refresh = QtWidgets.QPushButton("Обновить")
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Поиск: тикер / название / ISIN")

        row1 = QtWidgets.QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.addWidget(self.btn_refresh)
        row1.addWidget(self.search, 1)

        # ---- row 2: counts/status
        self.lbl_info = QtWidgets.QLabel("")
        self.lbl_info.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.lbl_info.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)

        # ---- instruments tabs (left)
        self.all_tabs = QtWidgets.QTabWidget()
        self.tbl_shares = self._make_all_table()
        self.tbl_bonds = self._make_all_table()
        self.tbl_etfs = self._make_all_table()

        self.all_tabs.addTab(self.tbl_shares, "Акции")
        self.all_tabs.addTab(self.tbl_bonds, "Облигации")
        self.all_tabs.addTab(self.tbl_etfs, "Фонды")

        # ---- favorites (right)
        self.btn_add_fav = QtWidgets.QPushButton("→ В избранное")
        self.btn_remove_fav = QtWidgets.QPushButton("Удалить")

        self.tbl_fav = QtWidgets.QTableWidget(0, 4)
        self.tbl_fav.setHorizontalHeaderLabels(["Type", "Ticker", "Name", "ISIN"])
        self.tbl_fav.horizontalHeader().setStretchLastSection(True)
        self.tbl_fav.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_fav.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        fav_btns = QtWidgets.QHBoxLayout()
        fav_btns.setContentsMargins(0, 0, 0, 0)
        fav_btns.addWidget(self.btn_add_fav)
        fav_btns.addWidget(self.btn_remove_fav)
        fav_btns.addStretch()

        fav_layout = QtWidgets.QVBoxLayout()
        fav_layout.setContentsMargins(0, 0, 0, 0)
        fav_layout.setSpacing(6)
        fav_layout.addLayout(fav_btns)
        fav_layout.addWidget(self.tbl_fav)

        fav_panel = QtWidgets.QWidget()
        fav_panel.setLayout(fav_layout)

        # ---- row 3: two tables area
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self.all_tabs)
        split.addWidget(fav_panel)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        # ---- main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        layout.addLayout(row1, 0)
        layout.addWidget(self.lbl_info, 0)
        layout.addWidget(split, 1)  # важно: растягиваем таблицы на всё оставшееся место

        # ---- controller -> UI
        self.controller.status_changed.connect(self._on_status_changed)
        self.controller.loading_changed.connect(self._on_loading_changed)
        self.controller.shares_updated.connect(self._on_shares_updated)
        self.controller.bonds_updated.connect(self._on_bonds_updated)
        self.controller.etfs_updated.connect(self._on_etfs_updated)
        self.controller.favorites_updated.connect(self._on_fav_updated)
        self.controller.error.connect(self._print_error)
        self.controller.emit_initial_state()

        # ---- UI actions
        self.btn_refresh.clicked.connect(self.controller.refresh)
        self.search.textChanged.connect(self._apply_filter)

        self.btn_add_fav.clicked.connect(self._add_selected_to_fav)
        self.btn_remove_fav.clicked.connect(self._remove_selected_from_fav)

        self.tbl_shares.cellDoubleClicked.connect(lambda *_: self._select_from_table(self.tbl_shares))
        self.tbl_bonds.cellDoubleClicked.connect(lambda *_: self._select_from_table(self.tbl_bonds))
        self.tbl_etfs.cellDoubleClicked.connect(lambda *_: self._select_from_table(self.tbl_etfs))
        self.tbl_fav.cellDoubleClicked.connect(lambda *_: self._select_from_table(self.tbl_fav))

    # -------- public --------

    def selected_instrument(self) -> Optional[InstrumentInfo]:
        return self._selected

    # -------- internal helpers --------

    def _make_all_table(self) -> QtWidgets.QTableWidget:
        t = QtWidgets.QTableWidget(0, 4)
        t.setHorizontalHeaderLabels(["Ticker", "Name", "ISIN", "★"])
        t.horizontalHeader().setStretchLastSection(True)
        t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        t.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        return t

    def _print_error(self, tb: str):
        print("===== ERROR (InstrumentPickerWidget) =====")
        print(tb)
        print("==========================================")

    def _on_loading_changed(self, is_loading: bool):
        self.btn_refresh.setEnabled(not is_loading)
        if is_loading:
            self.lbl_info.setText("Загрузка инструментов...")

    def _on_status_changed(self, text: str):
        # controller уже формирует строку вида:
        # "Акции: N | Облигации: M | ETF: K" или "Загрузка..."
        self.lbl_info.setText(text)

    def _set_row_info(self, table: QtWidgets.QTableWidget, row: int, info: InstrumentInfo):
        item = table.item(row, 0)
        if item is None:
            item = QtWidgets.QTableWidgetItem("")
            table.setItem(row, 0, item)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, info)

    def _selected_info(self, table: QtWidgets.QTableWidget) -> Optional[InstrumentInfo]:
        sel = table.selectionModel().selectedRows()
        if not sel:
            return None
        r = sel[0].row()
        item = table.item(r, 0)
        if not item:
            return None
        return item.data(QtCore.Qt.ItemDataRole.UserRole)

    def _select_from_table(self, table: QtWidgets.QTableWidget):
        info = self._selected_info(table)
        if not info:
            return
        self._selected = info
        self.instrument_selected.emit(info)

    def _current_all_table(self) -> QtWidgets.QTableWidget:
        idx = self.all_tabs.currentIndex()
        if idx == 0:
            return self.tbl_shares
        if idx == 1:
            return self.tbl_bonds
        return self.tbl_etfs

    # -------- data receive --------

    def _on_shares_updated(self, items: list[InstrumentInfo]):
        self._shares_cache = items
        self._apply_filter()

    def _on_bonds_updated(self, items: list[InstrumentInfo]):
        self._bonds_cache = items
        self._apply_filter()

    def _on_etfs_updated(self, items: list[InstrumentInfo]):
        self._etfs_cache = items
        self._apply_filter()

    # -------- fill tables --------

    def _fill_all_table(self, table: QtWidgets.QTableWidget, items: list[InstrumentInfo]):
        table.setRowCount(0)
        table.setSortingEnabled(False)

        for info in items:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QtWidgets.QTableWidgetItem(info.ticker))
            table.setItem(r, 1, QtWidgets.QTableWidgetItem(info.name))
            table.setItem(r, 2, QtWidgets.QTableWidgetItem(info.isin))
            table.setItem(r, 3, QtWidgets.QTableWidgetItem("★" if self.controller.is_favorite(info) else ""))
            self._set_row_info(table, r, info)

        table.setSortingEnabled(True)

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

        self._fill_all_table(self.tbl_shares, [x for x in self._shares_cache if ok(x)])
        self._fill_all_table(self.tbl_bonds, [x for x in self._bonds_cache if ok(x)])
        self._fill_all_table(self.tbl_etfs, [x for x in self._etfs_cache if ok(x)])

    def _on_fav_updated(self, favs: list[InstrumentInfo]):
        self.tbl_fav.setRowCount(0)
        self.tbl_fav.setSortingEnabled(False)

        for info in favs:
            r = self.tbl_fav.rowCount()
            self.tbl_fav.insertRow(r)
            self.tbl_fav.setItem(r, 0, QtWidgets.QTableWidgetItem(kind_to_short(info.kind)))
            self.tbl_fav.setItem(r, 1, QtWidgets.QTableWidgetItem(info.ticker))
            self.tbl_fav.setItem(r, 2, QtWidgets.QTableWidgetItem(info.name))
            self.tbl_fav.setItem(r, 3, QtWidgets.QTableWidgetItem(info.isin))
            self._set_row_info(self.tbl_fav, r, info)

        self.tbl_fav.setSortingEnabled(True)
        self._apply_filter()

        # авто-выбор первого избранного при старте
        if self._selected is None and self.tbl_fav.rowCount() > 0:
            self.tbl_fav.selectRow(0)
            info = self._selected_info(self.tbl_fav)
            if info is not None:
                self._selected = info
                self.instrument_selected.emit(info)

    # -------- favorites actions --------

    def _add_selected_to_fav(self):
        info = self._selected_info(self._current_all_table())
        if info:
            self.controller.add_favorite(info)

    def _remove_selected_from_fav(self):
        info = self._selected_info(self.tbl_fav)
        if info:
            self.controller.remove_favorite(info)
