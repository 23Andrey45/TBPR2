from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtWidgets

from app.config import DATA_DIR


class JournalTab(QtWidgets.QWidget):
    ORDERS_CACHE_FILE = DATA_DIR / "orders_cache.json"
    FILLS_CACHE_FILE = DATA_DIR / "fills_cache.json"

    def __init__(self, trading_context, parent=None):
        super().__init__(parent)
        self.trading_context = trading_context
        self._account_id = str(getattr(self.trading_context, "account_id", "") or "")

        self.lbl_title = QtWidgets.QLabel("Журнал заявок")
        self.btn_refresh = QtWidgets.QPushButton("Обновить")
        self.cb_all_accounts = QtWidgets.QCheckBox("Все аккаунты")
        self.lbl_status = QtWidgets.QLabel("")

        self.tbl = QtWidgets.QTableWidget(0, 10)
        self.tbl.setHorizontalHeaderLabels(
            [
                "Время",
                "Account",
                "Ticker",
                "Side",
                "Type",
                "Lots",
                "Price",
                "Status",
                "Source",
                "Order ID",
            ]
        )
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.lbl_title)
        top.addStretch()
        top.addWidget(self.cb_all_accounts)
        top.addWidget(self.btn_refresh)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tbl)
        layout.addWidget(self.lbl_status)

        self.btn_refresh.clicked.connect(self.refresh)
        self.cb_all_accounts.toggled.connect(lambda *_: self.refresh())
        if hasattr(self.trading_context, "account_changed"):
            self.trading_context.account_changed.connect(self._on_account_changed)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

        self.refresh()

    def stop(self):
        self._timer.stop()

    def _on_account_changed(self, account_id: str):
        self._account_id = str(account_id or "")
        self.refresh()

    def refresh(self):
        items = self._collect_items()

        self.tbl.setRowCount(0)
        for rec in items:
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            self.tbl.setItem(row, 0, QtWidgets.QTableWidgetItem(str(rec.get("time", ""))))
            self.tbl.setItem(row, 1, QtWidgets.QTableWidgetItem(str(rec.get("account_id", ""))))
            self.tbl.setItem(row, 2, QtWidgets.QTableWidgetItem(str(rec.get("ticker", ""))))
            self.tbl.setItem(row, 3, QtWidgets.QTableWidgetItem(str(rec.get("side", ""))))
            self.tbl.setItem(row, 4, QtWidgets.QTableWidgetItem(str(rec.get("order_type", ""))))
            self.tbl.setItem(row, 5, QtWidgets.QTableWidgetItem(str(rec.get("lots", ""))))
            self.tbl.setItem(row, 6, QtWidgets.QTableWidgetItem(str(rec.get("price", ""))))
            self.tbl.setItem(row, 7, QtWidgets.QTableWidgetItem(str(rec.get("status", ""))))
            self.tbl.setItem(row, 8, QtWidgets.QTableWidgetItem(str(rec.get("source", ""))))
            self.tbl.setItem(row, 9, QtWidgets.QTableWidgetItem(str(rec.get("order_id", ""))))

        self.lbl_status.setText(f"Записей: {len(items)}")

    def _collect_items(self) -> list[dict[str, Any]]:
        order_rows = self._load_orders()
        fill_rows = self._load_fills()

        out: list[dict[str, Any]] = []
        show_all = self.cb_all_accounts.isChecked()

        for row in order_rows:
            account_id = str(row.get("account_id", "") or "")
            if not show_all and self._account_id and account_id != self._account_id:
                continue

            out.append(
                {
                    "time": str(row.get("created_at", "") or ""),
                    "account_id": account_id,
                    "ticker": str(row.get("ticker", "") or ""),
                    "side": str(row.get("side", "") or ""),
                    "order_type": str(row.get("order_type", "") or ""),
                    "lots": int(row.get("lots_requested", 0) or 0),
                    "price": str(row.get("price", "") or ""),
                    "status": str(row.get("status_ui", "") or ""),
                    "source": "order-cache",
                    "order_id": str(row.get("order_id", "") or ""),
                }
            )

        for row in fill_rows:
            account_id = str(row.get("account_id", "") or "")
            if not show_all and self._account_id and account_id != self._account_id:
                continue

            out.append(
                {
                    "time": str(row.get("time", "") or ""),
                    "account_id": account_id,
                    "ticker": str(row.get("ticker", "") or ""),
                    "side": str(row.get("side", "") or ""),
                    "order_type": str(row.get("order_type", "") or ""),
                    "lots": row.get("lots", ""),
                    "price": str(row.get("price", "") or ""),
                    "status": str(row.get("status", "") or ""),
                    "source": str(row.get("source", "fill-cache") or "fill-cache"),
                    "order_id": str(row.get("order_id", "") or ""),
                }
            )

        out.sort(key=lambda x: self._parse_dt(x.get("time")), reverse=True)
        return out

    def _load_orders(self) -> list[dict[str, Any]]:
        payload = self._load_json(self.ORDERS_CACHE_FILE)
        items = payload.get("orders", []) if isinstance(payload, dict) else []
        return [x for x in items if isinstance(x, dict)]

    def _load_fills(self) -> list[dict[str, Any]]:
        payload = self._load_json(self.FILLS_CACHE_FILE)
        items = payload.get("fills", []) if isinstance(payload, dict) else []
        return [x for x in items if isinstance(x, dict)]

    def _load_json(self, path: Path) -> Any:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _parse_dt(self, value: Any) -> datetime:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return datetime.min