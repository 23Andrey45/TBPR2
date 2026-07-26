# history/tab_history.py
"""
Вкладка "История" - просмотр всех сделок из базы данных.
Поддерживает переключение между песочницей и реальным счётом.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Any

from PyQt6 import QtCore, QtWidgets

from app.config import TOKEN, REAL_TOKEN
# TODO: Добавить после загрузки db/
# from db import Fill, FillRepository, Order, OrderRepository
from app.workers import SandboxHistoryLoader
from trading.trading_context import TradingContext


def _log(msg: str):
    """Логирование."""
    print(f"[HistoryTab] {msg}")


# Заглушки для БД пока db не загружен
class Fill:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class Order:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FillRepository:
    @staticmethod
    def get_all(account_id: str, days: int = 3) -> list:
        """Заглушка - возвращает пустой список"""
        print(f"[FillRepository] get_all({account_id}, {days}) - not implemented (db not loaded)")
        return []


class OrderRepository:
    @staticmethod
    def get_all(account_id: str, days: int = 3) -> list:
        """Заглушка - возвращает пустой список"""
        print(f"[OrderRepository] get_all({account_id}, {days}) - not implemented (db not loaded)")
        return []


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

        # Обновляем таблицы
        self._render_fills_table(fills)
        self._render_orders_table(orders)

        self.lbl_total.setText(f"Всего: {len(fills)} сделок, {len(orders)} ордеров")
        self.lbl_status.setText(f"✅ Обновлено: {datetime.now().strftime('%H:%M:%S')}")

    def _render_fills_table(self, fills: list):
        """Отрисовка таблицы сделок."""
        self.tbl_fills.setRowCount(0)
        for f in fills:
            r = self.tbl_fills.rowCount()
            self.tbl_fills.insertRow(r)
            self.tbl_fills.setItem(r, 0, QtWidgets.QTableWidgetItem(self._format_time(f.time if hasattr(f, 'time') else f.get('time', ''))))
            self.tbl_fills.setItem(r, 1, QtWidgets.QTableWidgetItem(f.ticker if hasattr(f, 'ticker') else f.get('ticker', '')))
            self.tbl_fills.setItem(r, 2, QtWidgets.QTableWidgetItem(f.figi if hasattr(f, 'figi') else f.get('figi', '')))
            self.tbl_fills.setItem(r, 3, QtWidgets.QTableWidgetItem(f.side if hasattr(f, 'side') else f.get('side', '')))
            self.tbl_fills.setItem(r, 4, QtWidgets.QTableWidgetItem(str(f.lots if hasattr(f, 'lots') else f.get('lots', ''))))
            self.tbl_fills.setItem(r, 5, QtWidgets.QTableWidgetItem(str(f.price if hasattr(f, 'price') else f.get('price', ''))))
            self.tbl_fills.setItem(r, 6, QtWidgets.QTableWidgetItem(str(f.sum if hasattr(f, 'sum') else f.get('sum', ''))))
            self.tbl_fills.setItem(r, 7, QtWidgets.QTableWidgetItem(f.status if hasattr(f, 'status') else f.get('status', '')))
            self.tbl_fills.setItem(r, 8, QtWidgets.QTableWidgetItem(f.order_id if hasattr(f, 'order_id') else f.get('order_id', '')))
            self.tbl_fills.setItem(r, 9, QtWidgets.QTableWidgetItem(f.source if hasattr(f, 'source') else f.get('source', '')))

    def _render_orders_table(self, orders: list):
        """Отрисовка таблицы ордеров."""
        self.tbl_orders.setRowCount(0)
        for o in orders:
            r = self.tbl_orders.rowCount()
            self.tbl_orders.insertRow(r)
            self.tbl_orders.setItem(r, 0, QtWidgets.QTableWidgetItem(self._format_time(o.created_at if hasattr(o, 'created_at') else o.get('created_at', ''))))
            self.tbl_orders.setItem(r, 1, QtWidgets.QTableWidgetItem(o.ticker if hasattr(o, 'ticker') else o.get('ticker', '')))
            self.tbl_orders.setItem(r, 2, QtWidgets.QTableWidgetItem(o.figi if hasattr(o, 'figi') else o.get('figi', '')))
            self.tbl_orders.setItem(r, 3, QtWidgets.QTableWidgetItem(o.side if hasattr(o, 'side') else o.get('side', '')))
            self.tbl_orders.setItem(r, 4, QtWidgets.QTableWidgetItem(o.order_type if hasattr(o, 'order_type') else o.get('order_type', '')))
            self.tbl_orders.setItem(r, 5, QtWidgets.QTableWidgetItem(str(o.lots_requested if hasattr(o, 'lots_requested') else o.get('lots_requested', ''))))
            self.tbl_orders.setItem(r, 6, QtWidgets.QTableWidgetItem(str(o.lots_executed if hasattr(o, 'lots_executed') else o.get('lots_executed', ''))))
            self.tbl_orders.setItem(r, 7, QtWidgets.QTableWidgetItem(str(o.price if hasattr(o, 'price') else o.get('price', ''))))
            self.tbl_orders.setItem(r, 8, QtWidgets.QTableWidgetItem(o.status if hasattr(o, 'status') else o.get('status', '')))
            self.tbl_orders.setItem(r, 9, QtWidgets.QTableWidgetItem(o.order_id if hasattr(o, 'order_id') else o.get('order_id', '')))
            self.tbl_orders.setItem(r, 10, QtWidgets.QTableWidgetItem(o.message if hasattr(o, 'message') else o.get('message', '')))

    def _format_time(self, value: Any) -> str:
        """Форматирование времени."""
        if not value:
            return ""
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(value)

    def _start_load_history(self):
        """Загрузка истории с сервера."""
        if not self._account_id:
            self.lbl_status.setText("❌ Нет account_id")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Загрузка истории с сервера...")

        token = self._get_token()
        days = self._get_days_for_period(self.cb_filter_period.currentText())

        self._load_thread = QtCore.QThread(self)
        self._load_worker = SandboxHistoryLoader(token, self._account_id, days)
        self._load_worker.moveToThread(self._load_thread)

        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.loaded.connect(self._on_history_loaded)
        self._load_worker.progress.connect(self.progress_bar.setValue)
        self._load_worker.error.connect(self._on_history_error)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.finished.connect(self._cleanup_loader)

        self._load_thread.start()

    def _on_history_loaded(self, data: dict):
        """Обработка загруженных данных."""
        self.progress_bar.setVisible(False)
        fills = data.get("fills", [])
        orders = data.get("orders", [])
        count = data.get("count", 0)

        self.lbl_status.setText(f"✅ Загружено: {count} записей")
        self.lbl_total.setText(f"Всего: {len(fills)} сделок, {len(orders)} ордеров")

        # TODO: Сохранить в БД после загрузки db/
        _log(f"Loaded {len(fills)} fills, {len(orders)} orders")

    def _on_history_error(self, error: str):
        """Обработка ошибки загрузки."""
        self.progress_bar.setVisible(False)
        self.lbl_status.setText(f"❌ Ошибка: {error}")
        _log(f"Error loading history: {error}")

    def _cleanup_loader(self):
        """Очистка воркера."""
        self._load_thread = None
        self._load_worker = None
