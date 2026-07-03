# tabs/tab_account.py
from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtWidgets

from app.config import TOKEN
from core.sandbox_api import SandboxAccountInfo
from core.sandbox_trading_api import PortfolioRow
from tabs.workers import (
    SandboxAccountsLoader,
    SandboxOpenAccountLoader,
    SandboxPayInLoader,
    SandboxPortfolioLoader,
)


class AccountTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.btn_refresh = QtWidgets.QPushButton("Sandbox: обновить аккаунты")
        self.btn_open = QtWidgets.QPushButton("Sandbox: создать аккаунт")
        self.btn_payin = QtWidgets.QPushButton("Пополнить")
        self.btn_money = QtWidgets.QPushButton("Бумаги на счете")

        self.ed_units = QtWidgets.QLineEdit("100000")
        self.ed_units.setMaximumWidth(120)
        self.cb_currency = QtWidgets.QComboBox()
        self.cb_currency.addItems(["rub", "usd", "eur"])

        self.status = QtWidgets.QLabel("")

        self.tbl_accounts = QtWidgets.QTableWidget(0, 5)
        self.tbl_accounts.setHorizontalHeaderLabels(["account_id", "type", "status", "name", "opened_date"])
        self.tbl_accounts.horizontalHeader().setStretchLastSection(True)
        self.tbl_accounts.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_accounts.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        self.tbl_positions = QtWidgets.QTableWidget(0, 7)
        self.tbl_positions.setHorizontalHeaderLabels([
            "figi",
            "lots",
            "quantity",
            "avg_price",
            "cur_price",
            "yield",
            "currency",
        ])
        self.tbl_positions.horizontalHeader().setStretchLastSection(True)
        self.tbl_positions.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.btn_refresh)
        top.addWidget(self.btn_open)
        top.addSpacing(10)
        top.addWidget(QtWidgets.QLabel("Сумма:"))
        top.addWidget(self.ed_units)
        top.addWidget(self.cb_currency)
        top.addWidget(self.btn_payin)
        top.addWidget(self.btn_money)
        top.addWidget(self.status, 1)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        splitter.addWidget(self.tbl_accounts)
        splitter.addWidget(self.tbl_positions)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter)

        # обязательно держим ссылки, чтобы не “висло”
        self._thread: Optional[QtCore.QThread] = None
        self._worker = None

        self.btn_refresh.clicked.connect(self.refresh_accounts)
        self.btn_open.clicked.connect(self.open_account)
        self.btn_payin.clicked.connect(self.pay_in)
        self.btn_money.clicked.connect(self.load_money)

        self.tbl_accounts.itemSelectionChanged.connect(self._on_account_selection_changed)
        self._update_buttons()

    # ---------- utils ----------

    def _selected_account_id(self) -> Optional[str]:
        sel = self.tbl_accounts.selectionModel().selectedRows()
        if not sel:
            return None
        row = sel[0].row()
        item = self.tbl_accounts.item(row, 0)
        return item.text().strip() if item else None

    def _update_buttons(self):
        has_acc = bool(self._selected_account_id())
        self.btn_payin.setEnabled(has_acc)
        self.btn_money.setEnabled(has_acc)

    def _on_account_selection_changed(self):
        self._update_buttons()
        if self._selected_account_id():
            self.load_money()

    def _run_worker(self, worker, on_loaded=None):
        if self._thread and self._thread.isRunning():
            return

        self._thread = QtCore.QThread(self)
        self._worker = worker
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)

        if on_loaded is not None and hasattr(self._worker, "loaded"):
            self._worker.loaded.connect(on_loaded)

        if hasattr(self._worker, "error"):
            self._worker.error.connect(self._on_error)

        if hasattr(self._worker, "finished"):
            self._worker.finished.connect(self._thread.quit)
            self._worker.finished.connect(self._worker.deleteLater)

        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_finished)

        self._thread.start()

    def _on_finished(self):
        self._worker = None
        self._thread = None

    def _on_error(self, tb: str):
        self.status.setText("Ошибка (см. консоль)")
        print("===== ERROR (AccountTab sandbox) =====")
        print(tb)
        print("======================================")

    # ---------- actions ----------

    def refresh_accounts(self):
        self.status.setText("Загрузка sandbox аккаунтов...")
        self.tbl_accounts.setRowCount(0)
        self.tbl_positions.setRowCount(0)
        self._run_worker(SandboxAccountsLoader(TOKEN), self._on_accounts_loaded)

    def open_account(self):
        self.status.setText("Создание sandbox аккаунта...")
        self._run_worker(SandboxOpenAccountLoader(TOKEN), self._on_opened)

    def pay_in(self):
        acc_id = self._selected_account_id()
        if not acc_id:
            self.status.setText("Выберите аккаунт")
            return

        try:
            units = int(self.ed_units.text().strip())
        except Exception:
            self.status.setText("Сумма должна быть целым числом")
            return

        cur = self.cb_currency.currentText()
        self.status.setText(f"Пополнение {units} {cur} ...")

        self._run_worker(SandboxPayInLoader(TOKEN, acc_id, cur, units), self._on_payin_done)

    def load_money(self):
        acc_id = self._selected_account_id()
        if not acc_id:
            self.status.setText("Выберите аккаунт")
            return

        self.status.setText("Загрузка бумаг на счете...")
        self.tbl_positions.setRowCount(0)
        self._run_worker(SandboxPortfolioLoader(TOKEN, acc_id), self._on_money_loaded)

    # ---------- slots ----------

    def _on_accounts_loaded(self, accounts: list[SandboxAccountInfo]):
        self.status.setText(f"Аккаунтов: {len(accounts)}")
        self.tbl_accounts.setRowCount(0)

        for a in accounts:
            r = self.tbl_accounts.rowCount()
            self.tbl_accounts.insertRow(r)
            self.tbl_accounts.setItem(r, 0, QtWidgets.QTableWidgetItem(a.account_id))
            self.tbl_accounts.setItem(r, 1, QtWidgets.QTableWidgetItem(a.type))
            self.tbl_accounts.setItem(r, 2, QtWidgets.QTableWidgetItem(a.status))
            self.tbl_accounts.setItem(r, 3, QtWidgets.QTableWidgetItem(a.name))
            self.tbl_accounts.setItem(r, 4, QtWidgets.QTableWidgetItem(a.opened_date))

        if accounts:
            self.tbl_accounts.selectRow(0)
            self.load_money()

        self._update_buttons()

    def _on_opened(self, account_id: str):
        self.status.setText(f"Создан: {account_id}. Обновляю список...")
        # после создания обновим список
        self.refresh_accounts()

    def _on_payin_done(self):
        self.status.setText("Пополнено. Можно обновить деньги.")
        # опционально: сразу обновить деньги
        # self.load_money()

    def _on_money_loaded(self, rows: list[PortfolioRow]):
        self.status.setText(f"Позиции: {len(rows)}")
        self.tbl_positions.setRowCount(0)

        for p in rows:
            r = self.tbl_positions.rowCount()
            self.tbl_positions.insertRow(r)
            self.tbl_positions.setItem(r, 0, QtWidgets.QTableWidgetItem(p.figi))
            self.tbl_positions.setItem(r, 1, QtWidgets.QTableWidgetItem(f"{p.lots:.4f}"))
            self.tbl_positions.setItem(r, 2, QtWidgets.QTableWidgetItem(f"{p.quantity:.4f}"))
            self.tbl_positions.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{p.avg_price:.4f}"))
            self.tbl_positions.setItem(r, 4, QtWidgets.QTableWidgetItem(f"{p.current_price:.4f}"))
            self.tbl_positions.setItem(r, 5, QtWidgets.QTableWidgetItem(f"{p.expected_yield:.4f}"))
            cur = p.current_price_currency or p.avg_price_currency
            self.tbl_positions.setItem(r, 6, QtWidgets.QTableWidgetItem(cur))