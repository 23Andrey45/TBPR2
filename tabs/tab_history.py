# tabs/tab_history.py
"""
Вкладка "История" - просмотр всех сделок из базы данных.
Поддерживает переключение между песочницей и реальным счётом.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Any

from PyQt6 import QtCore, QtGui, QtWidgets

from app.config import DATA_DIR, TOKEN, REAL_TOKEN
from db import Fill, FillRepository, Order, OrderRepository
from app.workers import SandboxHistoryLoader
from tabs.trading_context import TradingContext


def _log(msg: str):
    """Логирование."""
    print(f"[HistoryTab] {msg}")


class HistoryTab(QtWidgets.QWidget):
    """Вкладка истории сделок."""

    def __init__(self, trading_context: TradingContext = None, parent=None):
        super().__init__(parent)

        self.trading_context = trading_context
        self._account_id = ""
        self._is_real_account = False  # Переключатель: False=песочница, True=реальный
        self._load_thread: Optional[QtCore.QThread] = None
        self._load_worker = None

        # ✅ Элементы управления
        self.btn_refresh = QtWidgets.QPushButton("🔄 Обновить")
        self.btn_refresh.setMaximumWidth(150)

        self.btn_load_history = QtWidgets.QPushButton("📥 Загрузить историю")
        self.btn_load_history.setMaximumWidth(200)

        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)

        self.lbl_total = QtWidgets.QLabel("Всего: 0")

        # ✅ Прогресс бар для загрузки
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(300)

        # Переключатель счёта
        self.account_type_combo = QtWidgets.QComboBox()
        self.account_type_combo.addItems(["Песочница", "Реальный счёт"])
        self.account_type_combo.setCurrentIndex(0)
        self.account_type_combo.setMaximumWidth(150)
        self.account_type_combo.currentIndexChanged.connect(self._on_account_type_changed)

        # Фильтры
        self.cb_filter_period = QtWidgets.QComboBox()
        self.cb_filter_period.addItems([
            "Все время",
            "За 3 дня",
            "За 7 дней",
            "За 30 дней",
            "За 90 дней",
        ])
        self.cb_filter_period.setCurrentIndex(1)  # По умолчанию 3 дня

        self.cb_filter_type = QtWidgets.QComboBox()
        self.cb_filter_type.addItems([
            "Все сделки",
            "Покупки",
            "Продажи",
        ])

        # ✅ Таблица сделок
        self.tbl_fills = QtWidgets.QTableWidget(0, 10)
        self.tbl_fills.setHorizontalHeaderLabels([
            "Время",
            "Ticker",
            "FIGI",
            "Side",
            "Lots",
            "Price",
            "Sum",
            "Status",
            "Order ID",
            "Source",
        ])
        self.tbl_fills.horizontalHeader().setStretchLastSection(True)
        self.tbl_fills.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_fills.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_fills.setAlternatingRowColors(True)

        # ✅ Таблица ордеров (вторая вкладка)
        self.tbl_orders = QtWidgets.QTableWidget(0, 11)
        self.tbl_orders.setHorizontalHeaderLabels([
            "Время",
            "Ticker",
            "FIGI",
            "Side",
            "Type",
            "Lots Req",
            "Lots Exec",
            "Price",
            "Status",
            "Order ID",
            "Message",
        ])
        self.tbl_orders.horizontalHeader().setStretchLastSection(True)
        self.tbl_orders.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_orders.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_orders.setAlternatingRowColors(True)

        # ✅ Вкладки: Сделки / Ордера
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.tbl_fills, "Сделки (Fills)")
        self.tabs.addTab(self.tbl_orders, "Ордера (Orders)")

        # ✅ Компоновка
        top_layout = QtWidgets.QHBoxLayout()
        top_layout.addWidget(self.btn_refresh)
        top_layout.addWidget(self.btn_load_history)
        top_layout.addWidget(self.progress_bar)
        top_layout.addWidget(QtWidgets.QLabel("Счёт:"))
        top_layout.addWidget(self.account_type_combo)
        top_layout.addWidget(QtWidgets.QLabel("Период:"))
        top_layout.addWidget(self.cb_filter_period)
        top_layout.addWidget(QtWidgets.QLabel("Тип:"))
        top_layout.addWidget(self.cb_filter_type)
        top_layout.addStretch()
        top_layout.addWidget(self.lbl_total)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_layout)
        layout.addWidget(self.lbl_status)
        layout.addWidget(self.tabs)

        # ✅ Подключения
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_load_history.clicked.connect(self._start_load_history)
        self.cb_filter_period.currentIndexChanged.connect(self.refresh)
        self.cb_filter_type.currentIndexChanged.connect(self.refresh)

        # ✅ Обновление account_id при изменении
        if self.trading_context:
            self.trading_context.account_changed.connect(self._on_account_changed)
            self._account_id = self.trading_context.account_id

        # ✅ Автообновление при открытии
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setInterval(30000)  # 30 секунд
        self._refresh_timer.timeout.connect(self.refresh)

        _log("HistoryTab initialized")

    def _on_account_type_changed(self, index: int):
        """Переключение между песочницей и реальным счётом."""
        self._is_real_account = (index == 1)
        account_type = "реальный" if self._is_real_account else "песочница"
        _log(f"Переключено на {account_type} счёт")
        self.refresh()

    def _on_account_changed(self, account_id: str):
        """Обновление account_id."""
        self._account_id = account_id
        _log(f"HistoryTab: account changed to {account_id}")

    def showEvent(self, event):
        """При показе вкладки - обновить данные."""
        super().showEvent(event)
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()
        QtCore.QTimer.singleShot(100, self.refresh)

    def hideEvent(self, event):
        """При скрытии вкладки - остановить таймер."""
        self._refresh_timer.stop()
        super().hideEvent(event)

    def _get_token(self) -> str:
        """Получить токен для текущего типа счёта."""
        return REAL_TOKEN if self._is_real_account else TOKEN

    def _get_days_for_period(self, period_text: str) -> int:
        """Получить количество дней для периода."""
        mapping = {
            "Все время": 3650,
            "За 3 дня": 3,
            "За 7 дней": 7,
            "За 30 дней": 30,
            "За 90 дней": 90,
        }
        return mapping.get(period_text, 30)

    def refresh(self):
        """Обновить отображение данных из БД."""
        if not self._account_id:
            self.lbl_status.setText("❌ Нет account_id")
            return

        days = self._get_days_for_period(self.cb_filter_period.currentText())
        filter_type = self.cb_filter_type.currentText()

        _log(f"Refreshing: account={self._account_id}, days={days}, type={filter_type}, real={self._is_real_account}")

        # Получаем данные из БД
        fills = FillRepository.get_all(self._account_id, days)
        orders = OrderRepository.get_all(self._account_id)

        # Применяем фильтры
        if filter_type == "Покупки":
            fills = [f for f in fills if f.side.lower() == "buy"]
        elif filter_type == "Продажи":
            fills = [f for f in fills if f.side.lower() == "sell"]

        # Отображаем сделки
        self.tbl_fills.setRowCount(0)
        for fill in fills:
            r = self.tbl_fills.rowCount()
            self.tbl_fills.insertRow(r)

            time_str = fill.time[:19] if fill.time else "-"
            self.tbl_fills.setItem(r, 0, QtWidgets.QTableWidgetItem(time_str))
            self.tbl_fills.setItem(r, 1, QtWidgets.QTableWidgetItem(fill.ticker or "-"))
            self.tbl_fills.setItem(r, 2, QtWidgets.QTableWidgetItem(fill.figi))

            side_item = QtWidgets.QTableWidgetItem(fill.side.upper())
            if fill.side.lower() == "buy":
                side_item.setForeground(QtGui.QColor("#4CAF50"))
            elif fill.side.lower() == "sell":
                side_item.setForeground(QtGui.QColor("#f44336"))
            self.tbl_fills.setItem(r, 3, side_item)

            self.tbl_fills.setItem(r, 4, QtWidgets.QTableWidgetItem(str(fill.lots)))
            self.tbl_fills.setItem(r, 5, QtWidgets.QTableWidgetItem(fill.price or "-"))

            # Sum = lots * price
            try:
                sum_val = fill.lots * float(fill.price) if fill.price else 0
                self.tbl_fills.setItem(r, 6, QtWidgets.QTableWidgetItem(f"{sum_val:.2f}"))
            except:
                self.tbl_fills.setItem(r, 6, QtWidgets.QTableWidgetItem("-"))

            self.tbl_fills.setItem(r, 7, QtWidgets.QTableWidgetItem(fill.status or "-"))
            self.tbl_fills.setItem(r, 8, QtWidgets.QTableWidgetItem(fill.order_id or "-"))
            self.tbl_fills.setItem(r, 9, QtWidgets.QTableWidgetItem(fill.source or "-"))

        # Отображаем ордера
        self.tbl_orders.setRowCount(0)
        for order in orders:
            r = self.tbl_orders.rowCount()
            self.tbl_orders.insertRow(r)

            time_str = order.created_at[:19] if order.created_at else "-"
            self.tbl_orders.setItem(r, 0, QtWidgets.QTableWidgetItem(time_str))
            self.tbl_orders.setItem(r, 1, QtWidgets.QTableWidgetItem(order.ticker or "-"))
            self.tbl_orders.setItem(r, 2, QtWidgets.QTableWidgetItem(order.figi))

            side_item = QtWidgets.QTableWidgetItem(order.side.upper())
            if order.side.lower() == "buy":
                side_item.setForeground(QtGui.QColor("#4CAF50"))
            elif order.side.lower() == "sell":
                side_item.setForeground(QtGui.QColor("#f44336"))
            self.tbl_orders.setItem(r, 3, side_item)

            self.tbl_orders.setItem(r, 4, QtWidgets.QTableWidgetItem(order.order_type))
            self.tbl_orders.setItem(r, 5, QtWidgets.QTableWidgetItem(str(order.lots_requested)))
            self.tbl_orders.setItem(r, 6, QtWidgets.QTableWidgetItem(str(order.lots_executed)))
            self.tbl_orders.setItem(r, 7, QtWidgets.QTableWidgetItem(order.price or "-"))

            status_item = QtWidgets.QTableWidgetItem(order.status_ui)
            if "Исполнена" in order.status_ui:
                status_item.setForeground(QtGui.QColor("#4CAF50"))
            elif "Отменена" in order.status_ui or "Отклонена" in order.status_ui:
                status_item.setForeground(QtGui.QColor("#999"))
            self.tbl_orders.setItem(r, 8, status_item)

            self.tbl_orders.setItem(r, 9, QtWidgets.QTableWidgetItem(order.order_id or "-"))
            self.tbl_orders.setItem(r, 10, QtWidgets.QTableWidgetItem(order.message or "-"))

        self.lbl_total.setText(f"Всего: {len(fills)} сделок, {len(orders)} ордеров")
        account_type = "реальный" if self._is_real_account else "песочница"
        self.lbl_status.setText(f"✅ Данные из БД ({account_type} счёт)")

    def _start_load_history(self):
        """Начать загрузку истории с сервера."""
        if not self._account_id:
            self.lbl_status.setText("❌ Нет account_id (выберите аккаунт в вкладке Торговля)")
            return

        # ✅ Диалог подтверждения
        days = self._get_days_for_period(self.cb_filter_period.currentText())
        account_type = "реального" if self._is_real_account else "песочницы"
        reply = QtWidgets.QMessageBox.question(
            self,
            "Загрузка истории",
            f"Загрузить историю сделок {account_type} счёта за последние {days} дн.?\n\n"
            f"Это может занять несколько минут.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No
        )

        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        # ✅ Запуск воркера
        token = self._get_token()
        self._load_thread = QtCore.QThread(self)
        self._load_worker = SandboxHistoryLoader(token, self._account_id, days)
        self._load_worker.moveToThread(self._load_thread)

        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.loaded.connect(self._on_history_loaded)
        self._load_worker.progress.connect(self.progress_bar.setValue)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.finished.connect(self._on_load_finished)

        # ✅ UI
        self.btn_load_history.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText(f"Загрузка истории {account_type} счёта с сервера...")

        self._load_thread.start()
        _log(f"HistoryTab: started loading history for {account_type} account")

    def _on_history_loaded(self, result: dict):
        """Обработка загруженной истории."""
        fills = result.get("fills", [])
        orders = result.get("orders", [])

        _log(f"HistoryTab: loaded {len(fills)} fills, {len(orders)} orders")

        # ✅ Сохранение в БД
        try:
            # Сохраняем сделки
            fill_objects = [Fill.from_dict(f) for f in fills]
            for fill in fill_objects:
                FillRepository.insert(fill)

            # Сохраняем ордера
            order_objects = [Order.from_dict(o) for o in orders]
            for order in order_objects:
                OrderRepository.insert(order)

            _log(f"HistoryTab: saved to DB")
            self.lbl_status.setText(f"✅ Загружено: {len(fills)} сделок, {len(orders)} ордеров")
            self.refresh()

        except Exception as e:
            _log(f"ERROR saving to DB: {e}")
            self.lbl_status.setText(f"❌ Ошибка сохранения в БД: {e}")

    def _on_load_error(self, error: str):
        """Обработка ошибки загрузки."""
        _log(f"ERROR: {error}")
        self.lbl_status.setText(f"❌ Ошибка: {error[:200]}")
        self.progress_bar.setVisible(False)
        self.btn_load_history.setEnabled(True)

    def _on_load_finished(self):
        """Завершение загрузки."""
        self.progress_bar.setVisible(False)
        self.btn_load_history.setEnabled(True)
        self._load_thread = None
        self._load_worker = None
