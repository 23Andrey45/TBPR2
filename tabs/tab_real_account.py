# tabs/tab_real_account.py
"""
Вкладка "Реальный счёт" - информация по реальному счёту с историей сделок.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from app.config import REAL_TOKEN, REAL_TOKEN_ERROR, REAL_TOKEN_FILE, FAVORITES_FILE
from core.account_api import get_accounts, get_portfolio, PortfolioPosition, AccountInfo
from core.operations_api import get_operations, save_operations_to_cache, load_operations_from_cache, Operation
from core.orders_api import get_orders, save_orders_to_cache, load_orders_from_cache, Order, clear_orders_cache
from core.instruments_catalog import InstrumentInfo
from core.favorites_repo import load_favorites, save_favorites


class RealAccountLoader(QtCore.QObject):
    """Загрузчик данных счёта в фоновом потоке."""
    loaded = QtCore.pyqtSignal(object)  # dict с account и portfolio
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    @QtCore.pyqtSlot()
    def run(self):
        try:
            print(f"[RealAccountLoader] Начинаем загрузку...")

            # Получаем список счетов
            print("[RealAccountLoader] Запрашиваем список счетов...")
            accounts = get_accounts(self.token)
            print(f"[RealAccountLoader] Получено счетов: {len(accounts)}")

            if not accounts:
                self.error.emit("Счета не найдены. Проверьте токен.")
                self.finished.emit()
                return

            # Берём первый открытый счёт
            account = None
            for acc in accounts:
                print(f"[RealAccountLoader] Счёт: {acc.account_id}, статус: {acc.status}")
                if acc.status == "Opened":
                    account = acc
                    break

            if not account:
                print("[RealAccountLoader] Нет открытых счетов, берём первый")
                account = accounts[0]

            print(f"[RealAccountLoader] Используем счёт: {account.account_id}")

            # Получаем портфель
            print("[RealAccountLoader] Запрашиваем портфель...")
            portfolio = get_portfolio(self.token, account.account_id)
            print(f"[RealAccountLoader] Получено позиций: {len(portfolio.positions)}")

            self.loaded.emit({
                "account": account,
                "portfolio": portfolio,
            })
        except Exception as e:
            import traceback
            print(f"[RealAccountLoader] Ошибка: {e}")
            print(traceback.format_exc())
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()


class HistoryLoader(QtCore.QObject):
    """Загрузчик истории операций в фоновом потоке."""
    loaded = QtCore.pyqtSignal(object)  # list[Operation]
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, figi: str, days: int = 365):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.figi = figi
        self.days = days

    @QtCore.pyqtSlot()
    def run(self):
        try:
            print(f"[HistoryLoader] Загрузка истории для {self.figi}...")

            # Сначала пробуем загрузить из кэша
            cached = load_operations_from_cache(self.account_id, self.figi)
            if cached:
                print(f"[HistoryLoader] Загружено из кэша: {len(cached)} операций")
                self.loaded.emit(cached)
                self.finished.emit()
                return

            # Загружаем с сервера
            to_date = datetime.now(timezone.utc)
            from_date = to_date - timedelta(days=self.days)

            print(f"[HistoryLoader] Запрашиваем историю с {from_date} по {to_date}...")
            operations = get_operations(self.token, self.account_id, from_date, to_date)

            # Фильтруем по инструменту
            if self.figi:
                operations = [op for op in operations if op.figi == self.figi]

            print(f"[HistoryLoader] Получено операций: {len(operations)}")

            # Сохраняем в кэш
            if operations:
                save_operations_to_cache(self.account_id, self.figi, operations)
                print(f"[HistoryLoader] Сохранено в кэш")

            self.loaded.emit(operations)
        except Exception as e:
            import traceback
            print(f"[HistoryLoader] Ошибка: {e}")
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()


class OrdersLoader(QtCore.QObject):
    """Загрузчик активных заявок в фоновом потоке."""
    loaded = QtCore.pyqtSignal(object)  # list[Order]
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str):
        super().__init__()
        self.token = token
        self.account_id = account_id

    @QtCore.pyqtSlot()
    def run(self):
        try:
            print(f"[OrdersLoader] Загрузка активных заявок...")

            # Загружаем с сервера (только активные, кэш не используем)
            print(f"[OrdersLoader] Запрашиваем активные заявки...")
            orders = get_orders(self.token, self.account_id)
            print(f"[OrdersLoader] Получено активных заявок: {len(orders)}")

            self.loaded.emit(orders)
        except Exception as e:
            import traceback
            print(f"[OrdersLoader] Ошибка: {e}")
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()


class RealAccountTab(QtWidgets.QWidget):
    """Вкладка реального счёта."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._account_thread: Optional[QtCore.QThread] = None
        self._account_worker: Optional[RealAccountLoader] = None
        self._history_thread: Optional[QtCore.QThread] = None
        self._history_worker: Optional[HistoryLoader] = None
        self._orders_thread: Optional[QtCore.QThread] = None
        self._orders_worker: Optional[OrdersLoader] = None

        self._portfolio_positions: list[PortfolioPosition] = []
        self._account_info: Optional[AccountInfo] = None
        self._current_figi: Optional[str] = None
        self._favorites: dict[str, InstrumentInfo] = {}
        self._all_orders: list[Order] = []
        self._current_operations: list[Operation] = []

        # Проверка токена
        if not REAL_TOKEN:
            layout = QtWidgets.QVBoxLayout(self)
            label = QtWidgets.QLabel(
                f"Токен реального счёта не загружен.\n\n"
                f"{REAL_TOKEN_ERROR}\n\n"
                f"Файл: {REAL_TOKEN_FILE}"
            )
            label.setWordWrap(True)
            label.setMargin(20)
            layout.addWidget(label)
            return

        # Основной layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Верхняя панель: информация о счёте + баланс
        top_panel = QtWidgets.QWidget()
        top_layout = QtWidgets.QHBoxLayout(top_panel)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(15)

        # Информация о счёте
        self.lbl_account_info = QtWidgets.QLabel("Загрузка...")
        self.lbl_account_info.setStyleSheet("font-weight: bold; font-size: 12px;")
        top_layout.addWidget(self.lbl_account_info, 1)

        # Разделитель
        separator = QtWidgets.QLabel("│")
        separator.setStyleSheet("color: #999; font-size: 12px;")
        top_layout.addWidget(separator)

        # Баланс портфеля
        balance_widget = QtWidgets.QWidget()
        balance_layout = QtWidgets.QHBoxLayout(balance_widget)
        balance_layout.setContentsMargins(0, 0, 0, 0)
        balance_layout.setSpacing(12)

        self.lbl_total = QtWidgets.QLabel("<b>Всего:</b> -")
        self.lbl_total.setStyleSheet("font-size: 12px; color: #2e7d32;")
        balance_layout.addWidget(self.lbl_total)

        self.lbl_shares = QtWidgets.QLabel("Акции: -")
        self.lbl_shares.setStyleSheet("font-size: 11px;")
        balance_layout.addWidget(self.lbl_shares)

        self.lbl_bonds = QtWidgets.QLabel("Обл: -")
        self.lbl_bonds.setStyleSheet("font-size: 11px;")
        balance_layout.addWidget(self.lbl_bonds)

        self.lbl_etf = QtWidgets.QLabel("ETF: -")
        self.lbl_etf.setStyleSheet("font-size: 11px;")
        balance_layout.addWidget(self.lbl_etf)

        self.lbl_currencies = QtWidgets.QLabel("Валюта: -")
        self.lbl_currencies.setStyleSheet("font-size: 11px;")
        balance_layout.addWidget(self.lbl_currencies)

        balance_layout.addStretch()
        top_layout.addWidget(balance_widget)
        main_layout.addWidget(top_panel)

        # Сплиттер: избранное слева, история справа
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)

        # Левая панель - избранное
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        left_header = QtWidgets.QLabel("📌 Избранное (реальный счёт)")
        left_header.setStyleSheet(
            "font-weight: bold; font-size: 11px; padding: 4px; background: #f5f5f5; border-radius: 3px;")
        left_layout.addWidget(left_header)

        self.fav_table = QtWidgets.QTableWidget(0, 4)
        self.fav_table.setHorizontalHeaderLabels(["Инструмент", "Кол-во", "Цена", "Стоимость"])
        self.fav_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fav_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.fav_table.verticalHeader().setVisible(False)
        self.fav_table.setAlternatingRowColors(True)

        # Последний столбец растягивается, остальные можно менять вручную
        header = self.fav_table.horizontalHeader()
        header.setSectionResizeMode(3,
                                    QtWidgets.QHeaderView.ResizeMode.Stretch)  # Стоимость - следует за размером панели

        left_layout.addWidget(self.fav_table)

        # ===== Правая панель - заявки и история сделок со сплиттером =====

        # Виджет для заявок
        orders_widget = QtWidgets.QWidget()
        orders_layout = QtWidgets.QVBoxLayout(orders_widget)
        orders_layout.setContentsMargins(0, 0, 0, 0)
        orders_layout.setSpacing(2)

        # Заголовок заявок + кнопка + статус в одну строку
        orders_header_layout = QtWidgets.QHBoxLayout()

        orders_header = QtWidgets.QLabel("📋 Активные заявки")
        orders_header.setStyleSheet("font-weight: bold; font-size: 11px; padding: 4px;")
        orders_header_layout.addWidget(orders_header)

        self.btn_refresh_orders = QtWidgets.QPushButton("🔄 Обновить")
        self.btn_refresh_orders.setMinimumHeight(22)
        self.btn_refresh_orders.setStyleSheet("""
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
        self.btn_refresh_orders.clicked.connect(self._refresh_orders)
        orders_header_layout.addWidget(self.btn_refresh_orders)

        self.lbl_orders_status = QtWidgets.QLabel("Заявок: 0")
        self.lbl_orders_status.setStyleSheet("color: #666; font-size: 10px;")
        orders_header_layout.addWidget(self.lbl_orders_status)
        orders_header_layout.addStretch()

        orders_layout.addLayout(orders_header_layout)

        # Таблица заявок
        self.orders_table = QtWidgets.QTableWidget(0, 7)
        self.orders_table.setHorizontalHeaderLabels(["Дата", "Тип", "Ticker", "Статус", "Кол-во", "Цена", "Исполнено"])
        self.orders_table.horizontalHeader().setStretchLastSection(True)
        self.orders_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.orders_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.orders_table.verticalHeader().setVisible(False)
        self.orders_table.setAlternatingRowColors(True)
        # Высота регулируется сплиттером
        orders_layout.addWidget(self.orders_table)

        # Виджет для истории
        history_widget = QtWidgets.QWidget()
        history_layout = QtWidgets.QVBoxLayout(history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(2)

        # Заголовок истории + кнопки в одну строку
        history_header_layout = QtWidgets.QHBoxLayout()

        history_header = QtWidgets.QLabel("📊 История сделок")
        history_header.setStyleSheet("font-weight: bold; font-size: 11px; padding: 4px;")
        history_header_layout.addWidget(history_header)

        history_header_layout.addStretch()

        self.btn_clear_cache = QtWidgets.QPushButton("🗑 Очистить кэш")
        self.btn_clear_cache.setMinimumHeight(22)
        self.btn_clear_cache.setToolTip("Очистить кэш истории и загрузить заново с тикерами")
        self.btn_clear_cache.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 9px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        self.btn_clear_cache.clicked.connect(self._clear_cache_and_reload)
        history_header_layout.addWidget(self.btn_clear_cache)

        self.btn_refresh_history = QtWidgets.QPushButton("🔄 Обновить")
        self.btn_refresh_history.setMinimumHeight(22)
        self.btn_refresh_history.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 9px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.btn_refresh_history.clicked.connect(self._refresh_history_for_selected)
        history_header_layout.addWidget(self.btn_refresh_history)

        history_layout.addLayout(history_header_layout)

        # Таблица истории
        self.history_table = QtWidgets.QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(["Дата", "Тип", "Ticker", "Кол-во", "Цена", "Сумма", "Валюта"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        history_layout.addWidget(self.history_table)

        # ===== Сплиттер между заявками и историей =====
        right_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        right_splitter.addWidget(orders_widget)
        right_splitter.addWidget(history_widget)
        right_splitter.setHandleWidth(6)
        right_splitter.setStretchFactor(0, 1)  # Заявки
        right_splitter.setStretchFactor(1, 2)  # История
        right_splitter.setSizes([200, 400])  # Начальные размеры

        # ===== Основная правая панель =====
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        # Фильтр по инструменту (над обеими таблицами)
        filter_panel = QtWidgets.QWidget()
        filter_panel.setStyleSheet("background: #e8f5e9; padding: 4px; border-radius: 3px;")
        filter_layout = QtWidgets.QHBoxLayout(filter_panel)
        filter_layout.setContentsMargins(4, 2, 4, 2)

        # Надпись о выбранном инструменте
        self.lbl_filter = QtWidgets.QLabel("Выберите инструмент в таблице слева")
        self.lbl_filter.setStyleSheet("color: #2e7d32; font-size: 10px; font-weight: bold;")
        filter_layout.addWidget(self.lbl_filter, 1)  # Растягивается

        # Чекбокс "только выбранное"
        self.chk_filter_enabled = QtWidgets.QCheckBox("только выбранное")
        self.chk_filter_enabled.setChecked(True)  # По умолчанию включен
        self.chk_filter_enabled.setStyleSheet("font-size: 10px; font-weight: bold;")
        self.chk_filter_enabled.setToolTip("Включите чтобы показывать данные только для выбранного инструмента")
        self.chk_filter_enabled.stateChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.chk_filter_enabled)

        right_layout.addWidget(filter_panel)
        right_layout.addWidget(right_splitter, 1)  # Растягивается

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([280, 720])  # Уменьшили с 350 до 280 (-20%)

        main_layout.addWidget(splitter, 1)

        # Нижняя панель
        bottom_panel = QtWidgets.QWidget()
        bottom_layout = QtWidgets.QHBoxLayout(bottom_panel)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_refresh = QtWidgets.QPushButton("🔄 Обновить данные счёта")
        self.btn_refresh.setMinimumHeight(30)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        bottom_layout.addWidget(self.btn_refresh)
        bottom_layout.addStretch()

        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setStyleSheet("color: #666; font-size: 10px;")
        bottom_layout.addWidget(self.lbl_status)

        main_layout.addWidget(bottom_panel)

        # Подключения
        self.btn_refresh.clicked.connect(self._refresh_account)
        self.fav_table.cellClicked.connect(self._on_fav_selected)

        # Загружаем избранное
        self._favorites = load_favorites(FAVORITES_FILE)

        # Автозагрузка
        self._refresh_account()

    def _refresh_account(self):
        """Обновить данные счёта."""
        if self._account_thread and self._account_thread.isRunning():
            return

        self.btn_refresh.setEnabled(False)
        self.lbl_account_info.setText("Загрузка...")
        self.lbl_status.setText("⏳ Запрос данных...")
        self.btn_refresh.setText("⏳ Загрузка...")

        self._account_thread = QtCore.QThread(self)
        self._account_worker = RealAccountLoader(REAL_TOKEN)
        self._account_worker.moveToThread(self._account_thread)

        self._account_thread.started.connect(self._account_worker.run)
        self._account_worker.loaded.connect(self._on_account_loaded)
        self._account_worker.error.connect(self._on_error)
        self._account_worker.finished.connect(self._account_thread.quit)
        self._account_worker.finished.connect(self._account_worker.deleteLater)
        self._account_thread.finished.connect(self._account_thread.deleteLater)
        self._account_thread.finished.connect(self._on_account_finished)

        self._account_thread.start()

    def _on_account_loaded(self, data: dict):
        """Обработка загруженных данных счёта."""
        self._account_info = data.get("account")
        portfolio = data.get("portfolio")

        if self._account_info:
            self.lbl_account_info.setText(
                f"💼 {self._account_info.account_id} ({self._account_info.account_type})"
            )

        if portfolio:
            self._portfolio_positions = portfolio.positions

            # Обновляем баланс
            total = portfolio.total_amount_portfolio
            self.lbl_total.setText(f"<b>Всего:</b> {total:,.2f} ₽")
            self.lbl_shares.setText(f"Акции: {portfolio.total_amount_shares:,.0f} ₽")
            self.lbl_bonds.setText(f"Обл: {portfolio.total_amount_bonds:,.0f} ₽")
            self.lbl_etf.setText(f"ETF: {portfolio.total_amount_etf:,.0f} ₽")
            self.lbl_currencies.setText(f"Валюта: {portfolio.total_amount_currencies:,.0f} ₽")

            # Обновляем таблицу избранного
            self._update_favorites_table()

        # Загружаем заявки
        self._refresh_orders()

    def _on_account_finished(self):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔄 Обновить данные счёта")

    def _update_favorites_table(self):
        """Обновить таблицу избранного с позициями реального счёта."""
        self.fav_table.setRowCount(0)

        # Создаём словарь FIGI -> позиция
        positions_by_figi = {pos.figi: pos for pos in self._portfolio_positions}

        for info in self._favorites.values():
            r = self.fav_table.rowCount()
            self.fav_table.insertRow(r)

            # Находим позицию по FIGI
            pos = positions_by_figi.get(info.figi)
            qty = pos.quantity if pos else 0.0
            price = pos.current_price if pos and pos.current_price else pos.position_avg_price if pos else 0.0
            value = qty * price if pos and pos.current_price else qty * pos.position_avg_price if pos else 0.0

            # Столбец "Инструмент" (Ticker + Name в двух строках)
            instrument_widget = QtWidgets.QWidget()
            instrument_widget.setToolTip(f"{info.ticker}\n{info.name or ''}")
            instrument_layout = QtWidgets.QVBoxLayout(instrument_widget)
            instrument_layout.setContentsMargins(4, 2, 4, 2)
            instrument_layout.setSpacing(0)

            # Ticker (жирный, синий)
            ticker_label = QtWidgets.QLabel(info.ticker)
            ticker_label.setStyleSheet("font-weight: bold; color: #1976d2; font-size: 11px;")
            ticker_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
            instrument_layout.addWidget(ticker_label)

            # Name (обычный, серый)
            name_label = QtWidgets.QLabel(info.name or "-")
            name_label.setStyleSheet("color: #666; font-size: 10px;")
            name_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
            instrument_layout.addWidget(name_label)

            # Добавляем обработку клика
            instrument_widget.mousePressEvent = lambda e, row=r: self._on_fav_widget_clicked(row)
            ticker_label.mousePressEvent = lambda e, row=r: self._on_fav_widget_clicked(row)
            name_label.mousePressEvent = lambda e, row=r: self._on_fav_widget_clicked(row)

            self.fav_table.setCellWidget(r, 0, instrument_widget)

            # Количество
            qty_item = QtWidgets.QTableWidgetItem(f"{qty:,.6f}")
            qty_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.fav_table.setItem(r, 1, qty_item)

            # Цена
            price_item = QtWidgets.QTableWidgetItem(f"{price:,.2f}" if price else "-")
            price_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.fav_table.setItem(r, 2, price_item)

            # Стоимость
            value_item = QtWidgets.QTableWidgetItem(f"{value:,.2f} ₽" if value else "-")
            value_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            value_item.setForeground(QtGui.QColor("#2e7d32"))
            self.fav_table.setItem(r, 3, value_item)

    def _on_fav_widget_clicked(self, row: int):
        """Обработка клика по виджету инструмента."""
        self._on_fav_selected(row, 0)

    def _on_fav_selected(self, row: int, column: int):
        """При выборе инструмента в избранном - загрузить историю."""
        if row < 0 or row >= self.fav_table.rowCount():
            return

        # Получаем widget из первой ячейки и извлекаем ticker
        instrument_widget = self.fav_table.cellWidget(row, 0)
        if not instrument_widget:
            return

        # Находим ticker label (первый QLabel в layout)
        ticker = None
        layout = instrument_widget.layout()
        if layout and layout.count() > 0:
            ticker_label = layout.itemAt(0).widget()
            if ticker_label:
                ticker = ticker_label.text()

        if not ticker:
            return

        # Находим InstrumentInfo по ticker
        info = None
        for fav_info in self._favorites.values():
            if fav_info.ticker == ticker:
                info = fav_info
                break

        if not info:
            self.lbl_filter.setText(f"Инструмент {ticker} не найден в избранном")
            return

        self._current_figi = info.figi
        self.lbl_filter.setText(f"📈 {info.ticker} | {info.name}")

        # Загружаем историю
        self._load_history(info.figi)

    def _load_history(self, figi: str):
        """Загрузить историю операций для инструмента."""
        if not self._account_info:
            self.lbl_filter.setText("Сначала загрузите данные счёта")
            return

        # Проверяем, не запущен ли уже поток
        if hasattr(self, '_history_thread') and self._history_thread and self._history_thread.isRunning():
            return

        self.history_table.setRowCount(0)
        self.lbl_status.setText(f"⏳ Загрузка истории для {figi}...")

        # Очищаем старые ссылки
        self._history_thread = None
        self._history_worker = None

        self._history_thread = QtCore.QThread(self)
        self._history_worker = HistoryLoader(REAL_TOKEN, self._account_info.account_id, figi, days=365)
        self._history_worker.moveToThread(self._history_thread)

        self._history_thread.started.connect(self._history_worker.run)
        self._history_worker.loaded.connect(self._on_history_loaded)
        self._history_worker.error.connect(self._on_history_error)
        self._history_worker.finished.connect(self._history_thread.quit)
        self._history_worker.finished.connect(self._history_worker.deleteLater)
        self._history_thread.finished.connect(self._on_history_thread_finished)
        self._history_thread.finished.connect(self._history_thread.deleteLater)

        self._history_thread.start()

    def _load_history_from_cache(self, figi: str):
        """Загрузить историю операций для инструмента из кэша (без сервера)."""
        if not self._account_info:
            return

        print(f"[RealAccountTab] Загрузка истории из кэша для {figi}...")

        # Загружаем из кэша
        operations = load_operations_from_cache(self._account_info.account_id, figi)

        if operations:
            print(f"[RealAccountTab] Загружено из кэша: {len(operations)} операций")
            self._on_history_loaded(operations)
            self.lbl_status.setText(f"📚 Из кэша: {len(operations)} операций")
        else:
            # Кэш пустой - показываем пустую таблицу
            self.history_table.setRowCount(0)
            self.lbl_status.setText(f"📚 Кэш пуст для {figi}. Нажмите 'Обновить' для загрузки.")
            print(f"[RealAccountTab] Кэш пуст для {figi}")

    def _on_history_thread_finished(self):
        """Очистка ссылок после завершения потока."""
        self._history_thread = None
        self._history_worker = None

    def _on_history_loaded(self, operations: list[Operation]):
        """Обработка загруженной истории."""
        # Сохраняем все операции для фильтрации
        self._current_operations = operations

        self.history_table.setRowCount(0)

        # Фильтруем по выбранному инструменту если выбран и чекбокс включен
        if self._current_figi and self.chk_filter_enabled.isChecked():
            operations = [op for op in operations if op.figi == self._current_figi]

        for op in operations:
            r = self.history_table.rowCount()
            self.history_table.insertRow(r)

            # Дата
            date_str = op.date.strftime("%Y-%m-%d %H:%M") if hasattr(op.date, "strftime") else str(op.date)
            self.history_table.setItem(r, 0, QtWidgets.QTableWidgetItem(date_str))

            # Тип операции (обрабатываем и строки, и числа из старого кэша)
            op_type_raw = op.operation_type
            if isinstance(op_type_raw, int):
                from core.operations_api import OPERATION_TYPE_MAP
                op_type = OPERATION_TYPE_MAP.get(op_type_raw, f"type_{op_type_raw}")
            else:
                op_type = str(op_type_raw)

            type_item = QtWidgets.QTableWidgetItem(op_type)
            op_type_lower = op_type.lower()
            if "buy" in op_type_lower:
                type_item.setForeground(QtGui.QColor("#f44336"))
            elif "sell" in op_type_lower:
                type_item.setForeground(QtGui.QColor("#4CAF50"))
            elif "dividend" in op_type_lower or "dividends" in op_type_lower:
                type_item.setForeground(QtGui.QColor("#2196F3"))
            elif "commission" in op_type_lower or "tax" in op_type_lower:
                type_item.setForeground(QtGui.QColor("#ff9800"))
            self.history_table.setItem(r, 1, type_item)

            # Ticker
            self.history_table.setItem(r, 2, QtWidgets.QTableWidgetItem(op.ticker or "-"))

            # Количество
            qty_item = QtWidgets.QTableWidgetItem(f"{op.quantity:,.6f}")
            qty_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(r, 3, qty_item)

            # Цена
            price_item = QtWidgets.QTableWidgetItem(f"{op.price:,.2f}")
            price_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(r, 4, price_item)

            # Сумма
            amount_item = QtWidgets.QTableWidgetItem(f"{op.amount:,.2f}")
            amount_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(r, 5, amount_item)

            # Валюта
            self.history_table.setItem(r, 6, QtWidgets.QTableWidgetItem(op.currency))

        self.lbl_status.setText(f"✅ Загружено операций: {len(operations)}")

    def _on_history_error(self, error: str):
        """Обработка ошибки загрузки истории."""
        self.lbl_status.setText(f"❌ Ошибка: {error[:50]}...")
        print(f"[RealAccountTab] History error: {error}")

    def _refresh_history_for_selected(self):
        """Обновить историю для выбранного инструмента."""
        if self._current_figi:
            self._load_history(self._current_figi)
        else:
            self.lbl_filter.setText("Сначала выберите инструмент в таблице слева")

    def _clear_cache(self):
        """Очистить кэш истории."""
        from core.operations_api import clear_history_cache
        clear_history_cache()
        self.lbl_status.setText("🗑 Кэш очищен")
        QtWidgets.QMessageBox.information(self, "Кэш", "Кэш истории операций очищен")

    def _clear_cache_and_reload(self):
        """Очистить кэш и перезагрузить историю для текущего инструмента."""
        from core.operations_api import clear_history_cache
        clear_history_cache()

        if self._current_figi:
            self.lbl_status.setText("🗑 Кэш очищен, загружаем заново...")
            self._load_history(self._current_figi)
            QtWidgets.QMessageBox.information(self, "Кэш", "Кэш очищен. История загружается заново с тикерами.")
        else:
            QtWidgets.QMessageBox.information(self, "Кэш", "Кэш очищен. Выберите инструмент для загрузки истории.")

    def _refresh_orders(self):
        """Обновить заявки."""
        if not self._account_info:
            self.lbl_orders_status.setText("Сначала загрузите данные счёта")
            return

        if self._orders_thread and self._orders_thread.isRunning():
            return

        self.btn_refresh_orders.setEnabled(False)
        self.lbl_orders_status.setText("⏳ Загрузка заявок...")

        # Очищаем старые ссылки
        self._orders_thread = None
        self._orders_worker = None

        self._orders_thread = QtCore.QThread(self)
        self._orders_worker = OrdersLoader(REAL_TOKEN, self._account_info.account_id)
        self._orders_worker.moveToThread(self._orders_thread)

        self._orders_thread.started.connect(self._orders_worker.run)
        self._orders_worker.loaded.connect(self._on_orders_loaded)
        self._orders_worker.error.connect(self._on_orders_error)
        self._orders_worker.finished.connect(self._orders_thread.quit)
        self._orders_worker.finished.connect(self._orders_worker.deleteLater)
        self._orders_thread.finished.connect(self._orders_thread.deleteLater)
        self._orders_thread.finished.connect(self._on_orders_finished)

        self._orders_thread.start()

    def _on_filter_changed(self, state):
        """Изменение состояния фильтра."""
        # Обновляем обе таблицы
        if self._all_orders:
            self._on_orders_loaded(self._all_orders)

        # Если есть загруженная история, обновляем её
        if hasattr(self, '_current_operations') and self._current_operations:
            self._on_history_loaded(self._current_operations)

    def _on_orders_loaded(self, orders: list[Order]):
        """Обработка загруженных заявок."""
        self._all_orders = orders

        self.orders_table.setRowCount(0)

        # Фильтруем по выбранному инструменту если выбран и чекбокс включен
        if self._current_figi and self.chk_filter_enabled.isChecked():
            orders = [o for o in orders if o.figi == self._current_figi]
            self.lbl_orders_status.setText(f"📈 {self._current_figi}: {len(orders)} заявок")
        else:
            if self._current_figi:
                self.lbl_orders_status.setText(f"✅ Все: {len(orders)} заявок (выбран {self._current_figi})")
            else:
                self.lbl_orders_status.setText(f"✅ Заявок: {len(orders)}")

        for order in orders:
            r = self.orders_table.rowCount()
            self.orders_table.insertRow(r)

            # Дата
            date_str = order.updated.strftime("%Y-%m-%d %H:%M") if order.updated else (
                order.created.strftime("%Y-%m-%d %H:%M") if order.created else "-")
            self.orders_table.setItem(r, 0, QtWidgets.QTableWidgetItem(date_str))

            # Тип заявки
            order_type = order.order_type.upper()
            type_item = QtWidgets.QTableWidgetItem(order_type)
            if order_type == "BUY":
                type_item.setForeground(QtGui.QColor("#f44336"))
            elif order_type == "SELL":
                type_item.setForeground(QtGui.QColor("#4CAF50"))
            self.orders_table.setItem(r, 1, type_item)

            # Ticker
            self.orders_table.setItem(r, 2, QtWidgets.QTableWidgetItem(order.ticker or "-"))

            # Статус
            status_item = QtWidgets.QTableWidgetItem(order.status)
            if "filled" in order.status.lower() or "executed" in order.status.lower():
                status_item.setForeground(QtGui.QColor("#4CAF50"))  # зелёный
            elif "cancelled" in order.status.lower() or "rejected" in order.status.lower():
                status_item.setForeground(QtGui.QColor("#999"))  # серый
            elif "partially" in order.status.lower():
                status_item.setForeground(QtGui.QColor("#ff9800"))  # оранжевый
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

        self.lbl_orders_status.setText(f"✅ Заявок: {len(orders)}")

    def _on_orders_error(self, error: str):
        """Обработка ошибки загрузки заявок."""
        self.lbl_orders_status.setText(f"❌ Ошибка: {error[:50]}...")
        print(f"[RealAccountTab] Orders error: {error}")

    def _on_orders_finished(self):
        """Завершение загрузки заявок."""
        self.btn_refresh_orders.setEnabled(True)
        self._orders_thread = None
        self._orders_worker = None

    def _on_fav_selected(self, row: int, column: int):
        """При выборе инструмента в избранном - загрузить историю и отфильтровать заявки."""
        if row < 0 or row >= self.fav_table.rowCount():
            return

        # Получаем widget из первой ячейки и извлекаем ticker
        instrument_widget = self.fav_table.cellWidget(row, 0)
        if not instrument_widget:
            return

        # Находим ticker label (первый QLabel в layout)
        ticker = None
        layout = instrument_widget.layout()
        if layout and layout.count() > 0:
            ticker_label = layout.itemAt(0).widget()
            if ticker_label:
                ticker = ticker_label.text()

        if not ticker:
            return

        # Находим InstrumentInfo по ticker
        info = None
        for fav_info in self._favorites.values():
            if fav_info.ticker == ticker:
                info = fav_info
                break

        if not info:
            self.lbl_filter.setText(f"Инструмент {ticker} не найден в избранном")
            return

        self._current_figi = info.figi
        filter_state = "включен" if self.chk_filter_enabled.isChecked() else "выключен"
        self.lbl_filter.setText(f"📈 {info.ticker} | {info.name} (фильтр: {filter_state})")

        # Обновляем отображение заявок с учётом фильтра
        if self._all_orders:
            self._on_orders_loaded(self._all_orders)

        # Загружаем историю из кэша (быстро, без сервера)
        self._load_history_from_cache(info.figi)

    def _on_error(self, error: str):
        """Обработка ошибки."""
        self._show_error_in_text_box(error)

    def _show_error_in_text_box(self, error: str):
        """Показать ошибку в текстовом поле."""
        # Очищаем текущий layout
        layout = self.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(self)
            self.setLayout(layout)

        # Создаём заголовок
        error_header = QtWidgets.QLabel("❌ Ошибка загрузки реального счёта:")
        error_header.setStyleSheet("font-weight: bold; font-size: 14px; color: red;")
        layout.insertWidget(0, error_header)

        # Создаём текстовое поле с ошибкой
        error_text = QtWidgets.QTextEdit()
        error_text.setReadOnly(True)
        error_text.setStyleSheet("""
            QTextEdit {
                background-color: #fff0f0;
                border: 1px solid #ff6b6b;
                border-radius: 4px;
                padding: 10px;
                font-family: Consolas, Monaco, monospace;
                font-size: 11px;
            }
        """)
        error_text.setPlainText(error)
        error_text.setMinimumHeight(300)
        layout.insertWidget(1, error_text)

        # Кнопка копирования
        copy_btn = QtWidgets.QPushButton("📋 Копировать ошибку")
        copy_btn.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(error_text.toPlainText()))
        layout.insertWidget(2, copy_btn)

        print("\n" + "=" * 60)
        print("ОШИБКА РЕАЛЬНОГО СЧЁТА:")
        print("=" * 60)
        print(error)
        print("=" * 60 + "\n")
