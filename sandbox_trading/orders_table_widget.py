# tabs/orders_table_widget.py
"""
Виджет таблицы "Активные заявки".
Может использоваться на разных вкладках.
"""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from core.orders_api import Order


class OrdersTableWidget(QtWidgets.QWidget):
    """Виджет таблицы активных заявок."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._orders: list[Order] = []

        # Заголовок
        header_label = QtWidgets.QLabel("📋 Активные заявки")
        header_label.setStyleSheet("font-weight: bold; font-size: 11px; padding: 4px; background: #e3f2fd; border-radius: 3px;")

        # Панель управления
        control_layout = QtWidgets.QHBoxLayout()
        control_layout.addStretch()

        self.btn_refresh = QtWidgets.QPushButton("🔄 Обновить")
        self.btn_refresh.setMinimumHeight(22)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #1976D2;
                color: white;
                border: none;
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 9px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1565C0;
            }
        """)
        control_layout.addWidget(self.btn_refresh)

        # Таблица
        self.orders_table = QtWidgets.QTableWidget(0, 7)
        self.orders_table.setHorizontalHeaderLabels([
            "Дата", "Тип", "Ticker", "Статус", "Кол-во", "Цена", "Исполнено"
        ])
        self.orders_table.horizontalHeader().setStretchLastSection(True)
        self.orders_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.orders_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.orders_table.verticalHeader().setVisible(False)
        self.orders_table.setAlternatingRowColors(True)

        # Статус
        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setStyleSheet("color: #666; font-size: 10px;")

        # Компоновка
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(header_label)
        layout.addLayout(control_layout)
        layout.addWidget(self.orders_table)
        layout.addWidget(self.lbl_status)

    def set_orders(self, orders: list[Order]):
        """Установить список заявок."""
        self._orders = orders
        self._update_table()

    def _update_table(self):
        """Обновить таблицу."""
        self.orders_table.setRowCount(0)

        for order in self._orders:
            r = self.orders_table.rowCount()
            self.orders_table.insertRow(r)

            # Дата
            date_str = order.updated.strftime("%Y-%m-%d %H:%M") if order.updated else (order.created.strftime("%Y-%m-%d %H:%M") if order.created else "-")
            self.orders_table.setItem(r, 0, QtWidgets.QTableWidgetItem(date_str))

            # Тип заявки
            order_type = order.order_type if order.order_type else ""
            type_item = QtWidgets.QTableWidgetItem(order_type)
            if "BUY" in order_type:
                type_item.setForeground(QtGui.QColor("#4CAF50"))
            elif "SELL" in order_type:
                type_item.setForeground(QtGui.QColor("#f44336"))
            self.orders_table.setItem(r, 1, type_item)

            # Ticker
            self.orders_table.setItem(r, 2, QtWidgets.QTableWidgetItem(order.ticker or "-"))

            # Статус
            status_item = QtWidgets.QTableWidgetItem(order.status)
            if "filled" in order.status.lower() or "executed" in order.status.lower():
                status_item.setForeground(QtGui.QColor("#4CAF50"))
            elif "cancelled" in order.status.lower() or "rejected" in order.status.lower():
                status_item.setForeground(QtGui.QColor("#999"))
            self.orders_table.setItem(r, 3, status_item)

            # Количество
            qty_item = QtWidgets.QTableWidgetItem(f"{order.lots_requested:,.0f}")
            qty_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.orders_table.setItem(r, 4, qty_item)

            # Цена
            price_item = QtWidgets.QTableWidgetItem(f"{order.price:,.2f}")
            price_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.orders_table.setItem(r, 5, price_item)

            # Исполнено
            exec_item = QtWidgets.QTableWidgetItem(f"{order.lots_executed:,.0f}")
            exec_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.orders_table.setItem(r, 6, exec_item)

        self.lbl_status.setText(f"✅ Заявок: {len(self._orders)}")

    def clear(self):
        """Очистить таблицу."""
        self._orders = []
        self.orders_table.setRowCount(0)
        self.lbl_status.setText("")
