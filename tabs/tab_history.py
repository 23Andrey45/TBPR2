# tabs/tab_history.py
"""
Вкладка "История" - просмотр всех сделок из базы данных.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Any

from PyQt6 import QtCore, QtWidgets

from app.config import DATA_DIR, TOKEN
from db import Fill, FillRepository, Order, OrderRepository
from workers import SandboxHistoryLoader
from tabs.trading_context import TradingContext


class HistoryTab(QtWidgets.QWidget):
    """Вкладка истории сделок."""

    def __init__(self, trading_context: TradingContext = None, parent=None):
        super().__init__(parent)

        self.trading_context = trading_context
        self._account_id = ""
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

    def _start_load_history(self):
        """Начать загрузку истории с сервера."""
        if not self._account_id:
            self.lbl_status.setText("❌ Нет account_id (выберите аккаунт в вкладке Торговля)")
            return

        # ✅ Диалог подтверждения
        days = self._get_days_for_period(self.cb_filter_period.currentText())
        reply = QtWidgets.QMessageBox.question(
            self,
            "Загрузка истории",
            f"Загрузить историю сделок за последние {days} дн.?\n\n"
            f"Это может занять несколько минут.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No
        )

        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        # ✅ Запуск воркера
        self._load_thread = QtCore.QThread(self)
        self._load_worker = SandboxHistoryLoader(TOKEN, self._account_id, days)
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
        self.lbl_status.setText("Загрузка истории с сервера...")

        self._load_thread.start()
        _log("HistoryTab: started loading history")

    def _on_history_loaded(self, result: dict):
        """Обработка загруженной истории."""
        fills = result.get("fills", [])
        orders = result.get("orders", [])

        _log(f"HistoryTab: loaded {len(fills)} fills, {len(orders)} orders")

        # ✅ Сохранение в БД
        try:
            # Сохраняем сделки
            fill_objects = [Fill.from_dict(f) for f in fills]
            FillRepository.insert_many(fill_objects)

            # Сохраняем ордера
            for o in orders:
                OrderRepository.insert(Order.from_dict(o))

            self.lbl_status.setText(f"✅ Загружено: {len(fills)} сделок, {len(orders)} ордеров")
            self.refresh()

        except Exception as e:
            _log(f"HistoryTab: save error: {e}")
            self.lbl_status.setText(f"❌ Ошибка сохранения: {e}")

    def _on_load_error(self, err: str):
        """Обработка ошибки загрузки."""
        _log(f"HistoryTab: load error: {err}")
        self.lbl_status.setText(f"❌ Ошибка загрузки: {err[:100]}")

    def _on_load_finished(self):
        """Завершение загрузки."""
        self.btn_load_history.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._load_thread = None
        self._load_worker = None

    def refresh(self):
        """Обновить данные из базы."""
        _log("HistoryTab: refresh START")

        try:
            # ✅ Получаем период
            period_text = self.cb_filter_period.currentText()
            days = self._get_days_for_period(period_text)

            # ✅ Получаем тип сделки
            type_text = self.cb_filter_type.currentText()
            side_filter = None
            if type_text == "Покупки":
                side_filter = "BUY"
            elif type_text == "Продажи":
                side_filter = "SELL"

            # ✅ Загружаем сделки
            fills = self._load_fills(days, side_filter)
            self._render_fills(fills)

            # ✅ Загружаем ордера
            orders = self._load_orders(days, side_filter)
            self._render_orders(orders)

            # ✅ Статус
            total = len(fills) + len(orders)
            self.lbl_total.setText(f"Всего: {total}")
            self.lbl_status.setText(
                f"Период: {period_text} | "
                f"Сделки: {len(fills)} | "
                f"Ордера: {len(orders)}"
            )

            _log(f"HistoryTab: refresh DONE - {len(fills)} fills, {len(orders)} orders")

        except Exception as e:
            _log(f"HistoryTab: refresh ERROR: {e}")
            import traceback
            traceback.print_exc()
            self.lbl_status.setText(f"Ошибка: {e}")

    def _get_days_for_period(self, period_text: str) -> int:
        """Получить количество дней для периода."""
        mapping = {
            "Все время": 3650,  # 10 лет
            "За 3 дня": 3,
            "За 7 дней": 7,
            "За 30 дней": 30,
            "За 90 дней": 90,
        }
        return mapping.get(period_text, 3)

    def _load_fills(self, days: int, side_filter: Optional[str] = None) -> list[Fill]:
        """Загрузить сделки из БД."""
        try:
            fills = FillRepository.get_all("", days=days)

            if side_filter:
                fills = [f for f in fills if f.side == side_filter]

            # Сортировка по времени (новые сверху)
            fills.sort(key=lambda x: x.time or "", reverse=True)

            return fills
        except Exception as e:
            _log(f"_load_fills ERROR: {e}")
            return []

    def _load_orders(self, days: int, side_filter: Optional[str] = None) -> list[Order]:
        """Загрузить ордера из БД."""
        try:
            orders = OrderRepository.get_all("")

            # Фильтр по времени
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            orders = [o for o in orders if o.created_at >= cutoff]

            if side_filter:
                orders = [o for o in orders if o.side == side_filter]

            # Сортировка по времени (новые сверху)
            orders.sort(key=lambda x: x.created_at or "", reverse=True)

            return orders
        except Exception as e:
            _log(f"_load_orders ERROR: {e}")
            return []

    def _render_fills(self, fills: list[Fill]):
        """Отрисовать таблицу сделок."""
        self.tbl_fills.setUpdatesEnabled(False)
        self.tbl_fills.blockSignals(True)

        try:
            self.tbl_fills.setRowCount(0)

            for fill in fills:
                r = self.tbl_fills.rowCount()
                self.tbl_fills.insertRow(r)

                # Время
                time_str = self._format_time(fill.time)
                self.tbl_fills.setItem(r, 0, QtWidgets.QTableWidgetItem(time_str))

                # Ticker
                self.tbl_fills.setItem(r, 1, QtWidgets.QTableWidgetItem(fill.ticker or fill.figi))

                # FIGI
                self.tbl_fills.setItem(r, 2, QtWidgets.QTableWidgetItem(fill.figi))

                # Side
                side_item = QtWidgets.QTableWidgetItem(fill.side)
                side_item.setForeground(
                    QtCore.Qt.GlobalColor.darkGreen if fill.side == "BUY" else QtCore.Qt.GlobalColor.darkRed)
                self.tbl_fills.setItem(r, 3, side_item)

                # Lots
                self.tbl_fills.setItem(r, 4, QtWidgets.QTableWidgetItem(str(fill.lots)))

                # Price
                self.tbl_fills.setItem(r, 5, QtWidgets.QTableWidgetItem(fill.price or ""))

                # Sum
                sum_val = ""
                if fill.price and fill.lots:
                    try:
                        sum_val = f"{float(fill.price) * fill.lots:.2f}"
                    except:
                        pass
                self.tbl_fills.setItem(r, 6, QtWidgets.QTableWidgetItem(sum_val))

                # Status
                self.tbl_fills.setItem(r, 7, QtWidgets.QTableWidgetItem(fill.status or ""))

                # Order ID
                self.tbl_fills.setItem(r, 8, QtWidgets.QTableWidgetItem(fill.order_id or ""))

                # Source
                self.tbl_fills.setItem(r, 9, QtWidgets.QTableWidgetItem(fill.source or ""))

            _log(f"_render_fills: {len(fills)} rows")

        finally:
            self.tbl_fills.blockSignals(False)
            self.tbl_fills.setUpdatesEnabled(True)
            self.tbl_fills.viewport().update()

    def _render_orders(self, orders: list[Order]):
        """Отрисовать таблицу ордеров."""
        self.tbl_orders.setUpdatesEnabled(False)
        self.tbl_orders.blockSignals(True)

        try:
            self.tbl_orders.setRowCount(0)

            for order in orders:
                r = self.tbl_orders.rowCount()
                self.tbl_orders.insertRow(r)

                # Время
                time_str = self._format_time(order.created_at)
                self.tbl_orders.setItem(r, 0, QtWidgets.QTableWidgetItem(time_str))

                # Ticker
                self.tbl_orders.setItem(r, 1, QtWidgets.QTableWidgetItem(order.ticker or order.figi))

                # FIGI
                self.tbl_orders.setItem(r, 2, QtWidgets.QTableWidgetItem(order.figi))

                # Side
                side_item = QtWidgets.QTableWidgetItem(order.side)
                side_item.setForeground(
                    QtCore.Qt.GlobalColor.darkGreen if order.side == "BUY" else QtCore.Qt.GlobalColor.darkRed)
                self.tbl_orders.setItem(r, 3, side_item)

                # Type
                self.tbl_orders.setItem(r, 4, QtWidgets.QTableWidgetItem(order.order_type))

                # Lots Req
                self.tbl_orders.setItem(r, 5, QtWidgets.QTableWidgetItem(str(order.lots_requested)))

                # Lots Exec
                self.tbl_orders.setItem(r, 6, QtWidgets.QTableWidgetItem(str(order.lots_executed)))

                # Price
                self.tbl_orders.setItem(r, 7, QtWidgets.QTableWidgetItem(order.price or ""))

                # Status
                self.tbl_orders.setItem(r, 8, QtWidgets.QTableWidgetItem(order.status_ui or ""))

                # Order ID
                self.tbl_orders.setItem(r, 9, QtWidgets.QTableWidgetItem(order.order_id or ""))

                # Message
                self.tbl_orders.setItem(r, 10, QtWidgets.QTableWidgetItem(order.message or ""))

            _log(f"_render_orders: {len(orders)} rows")

        finally:
            self.tbl_orders.blockSignals(False)
            self.tbl_orders.setUpdatesEnabled(True)
            self.tbl_orders.viewport().update()

    def _format_time(self, time_str: str) -> str:
        """Форматировать время в МСК."""
        if not time_str:
            return ""

        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            # Перевод в МСК (UTC+3)
            dt_msk = dt + timedelta(hours=3)
            return dt_msk.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return time_str


def _log(msg: str):
    """Логирование."""
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[HISTORY-TAB {ts}] {msg}")
