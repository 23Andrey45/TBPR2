# real_account/plan_controller.py
"""
Контроллер для управления таблицей "План заявок".
"""
from __future__ import annotations

from typing import Optional, Callable

from PyQt6 import QtCore, QtGui, QtWidgets

from real_account.plan_models import PlanOrder, PlanOrderStatus
from real_account.plan_repo import load_plan, save_plan, update_plan_order
from core.orders_api import Order
from core.trading_api import post_order


class PlanController:
    """
    Контроллер для управления планом заявок.

    Атрибуты:
        plan_table: QTableWidget для отображения плана
        get_account_info: функция для получения info о счёте
        on_refresh_orders: callback для обновления заявок
    """

    def __init__(
            self,
            plan_table: QtWidgets.QTableWidget,
            get_account_info: Callable[[], Optional[object]],
            on_refresh_orders: Callable[[], None],
            token: str,
    ):
        self.plan_table = plan_table
        self._get_account_info = get_account_info
        self._on_refresh_orders = on_refresh_orders
        self._token = token
        self._plan_orders: list[PlanOrder] = []

    def load(self) -> None:
        """Загрузить план из файла."""
        self._plan_orders = load_plan()
        self._update_table()

    def _update_table(self) -> None:
        """Обновить таблицу."""
        self.plan_table.setRowCount(len(self._plan_orders))

        for row, order in enumerate(self._plan_orders):
            self.plan_table.setItem(row, 0, QtWidgets.QTableWidgetItem(order.ticker or order.figi))

            direction_text = "Покупка" if order.direction.lower() == "buy" else "Продажа"
            direction_color = "#4CAF50" if order.direction.lower() == "buy" else "#f44336"
            item = QtWidgets.QTableWidgetItem(direction_text)
            item.setForeground(QtGui.QColor(direction_color))
            self.plan_table.setItem(row, 1, item)

            self.plan_table.setItem(row, 2, QtWidgets.QTableWidgetItem(f"{order.quantity:.0f}"))

            price_text = f"{order.price:.2f}" if order.order_type.lower() == "limit" else "Рынок"
            self.plan_table.setItem(row, 3, QtWidgets.QTableWidgetItem(price_text))

            type_text = "Лимит" if order.order_type.lower() == "limit" else "Рынок"
            self.plan_table.setItem(row, 4, QtWidgets.QTableWidgetItem(type_text))

            status_text = self._get_status_text(order.status)
            status_color = self._get_status_color(order.status)
            item = QtWidgets.QTableWidgetItem(status_text)
            item.setForeground(QtGui.QColor(status_color))
            self.plan_table.setItem(row, 5, item)

            btn_widget = self._create_button_widget(order)
            self.plan_table.setCellWidget(row, 6, btn_widget)

        self.plan_table.resizeRowsToContents()

    def _get_status_text(self, status: str) -> str:
        status_map = {
            PlanOrderStatus.PENDING.value: "Ожидает",
            PlanOrderStatus.SUBMITTED.value: "Выставлена",
            PlanOrderStatus.FILLED.value: "Исполнена",
            PlanOrderStatus.CANCELLED.value: "Отменена",
            PlanOrderStatus.REJECTED.value: "Отклонена",
        }
        return status_map.get(status, status)

    def _get_status_color(self, status: str) -> str:
        color_map = {
            PlanOrderStatus.PENDING.value: "#FF9800",
            PlanOrderStatus.SUBMITTED.value: "#2196F3",
            PlanOrderStatus.FILLED.value: "#4CAF50",
            PlanOrderStatus.CANCELLED.value: "#9E9E9E",
            PlanOrderStatus.REJECTED.value: "#f44336",
        }
        return color_map.get(status, "#000000")

    def _create_button_widget(self, order: PlanOrder) -> QtWidgets.QWidget:
        btn_widget = QtWidgets.QWidget()
        btn_layout = QtWidgets.QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(4, 2, 4, 2)

        if order.can_submit():
            btn_submit = QtWidgets.QPushButton("➕ Создать")
            btn_submit.setMinimumHeight(22)
            btn_submit.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                    border: none;
                    padding: 2px 8px;
                    border-radius: 3px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #1976D2;
                }
            """)
            btn_submit.clicked.connect(
                lambda checked, o=order: self._on_submit_clicked(o)
            )
            btn_layout.addWidget(btn_submit)
        else:
            lbl = QtWidgets.QLabel("—")
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            btn_layout.addWidget(lbl)

        btn_layout.addStretch()
        return btn_widget

    def _on_submit_clicked(self, plan_order: PlanOrder) -> None:
        account_info = self._get_account_info()
        if not account_info:
            QtWidgets.QMessageBox.warning(
                None, "Ошибка", "Счёт не загружен. Обновите данные счёта."
            )
            return

        if plan_order.status == PlanOrderStatus.CANCELLED.value:
            plan_order.reset_to_pending()
            update_plan_order(plan_order)

        result = post_order(
            token=self._token,
            account_id=account_info.account_id,
            figi=plan_order.figi,
            quantity=int(plan_order.quantity),
            price=plan_order.price,
            direction=plan_order.direction,
            order_type=plan_order.order_type,
        )

        if result.success:
            plan_order.mark_submitted(result.order_id)
            update_plan_order(plan_order)
            self._update_table()
            QtWidgets.QMessageBox.information(
                None, "Заявка выставлена",
                f"Заявка успешно выставлена на сервер.\nID: {result.order_id}"
            )
            self._on_refresh_orders()
        else:
            plan_order.mark_rejected()
            update_plan_order(plan_order)
            self._update_table()
            QtWidgets.QMessageBox.critical(
                None, "Ошибка",
                f"Не удалось выставить заявку:\n{result.error}"
            )

    def add_order(self, order: PlanOrder) -> None:
        """Добавить заявку в план."""
        self._plan_orders.insert(0, order)
        save_plan(self._plan_orders)
        self._update_table()

    def sync_with_orders(self, server_orders: list[Order]) -> None:
        """Синхронизировать план с заявками на сервере."""
        updated = False
        for plan_order in self._plan_orders:
            if plan_order.status == PlanOrderStatus.SUBMITTED.value and plan_order.server_order_id:
                for so in server_orders:
                    if so.order_id == plan_order.server_order_id:
                        if so.status.lower() in ("cancelled", "отменена"):
                            if plan_order.status != PlanOrderStatus.CANCELLED.value:
                                plan_order.mark_cancelled()
                                updated = True
                        elif so.status.lower() in ("filled", "исполнена"):
                            if plan_order.status != PlanOrderStatus.FILLED.value:
                                plan_order.mark_filled()
                                updated = True
                        break
        if updated:
            save_plan(self._plan_orders)
            self._update_table()
