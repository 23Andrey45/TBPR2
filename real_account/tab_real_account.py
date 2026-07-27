# real_account/tab_real_account.py
"""
Вкладка "Реальный счёт" - информация по реальному счёту с торговой панелью.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional, TYPE_CHECKING

from PyQt6 import QtCore, QtGui, QtWidgets

from app.config import REAL_TOKEN, REAL_TOKEN_ERROR, REAL_TOKEN_FILE, FAVORITES_FILE
from app.app_context import AppContext
from core.account_api import get_accounts, get_portfolio, PortfolioPosition, AccountInfo
from core.operations_api import get_operations, save_operations_to_cache, load_operations_from_cache, Operation
from core.orders_api import get_orders, Order
from core.instruments_catalog import InstrumentInfo
from core.favorites_repo import load_favorites
from core.trading_api import post_order

if TYPE_CHECKING:
    from market_data.quotes_hub import QuotesHub


class RealAccountLoader(QtCore.QObject):
    """Загрузчик данных счёта в фоновом потоке."""
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    @QtCore.pyqtSlot()
    def run(self):
        try:
            print(f"[RealAccountLoader] Начинаем загрузку...")
            accounts = get_accounts(self.token)
            print(f"[RealAccountLoader] Получено счетов: {len(accounts)}")

            if not accounts:
                self.error.emit("Счета не найдены. Проверьте токен.")
                self.finished.emit()
                return

            account = None
            for acc in accounts:
                if acc.status == "Opened":
                    account = acc
                    break

            if not account:
                account = accounts[0]

            print(f"[RealAccountLoader] Используем счёт: {account.account_id}")
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
    loaded = QtCore.pyqtSignal(object)
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
            cached = load_operations_from_cache(self.account_id, self.figi)
            if cached:
                print(f"[HistoryLoader] Загружено из кэша: {len(cached)} операций")
                self.loaded.emit(cached)
                self.finished.emit()
                return

            to_date = datetime.now(timezone.utc)
            from_date = to_date - timedelta(days=self.days)
            print(f"[HistoryLoader] Запрашиваем историю с {from_date} по {to_date}...")
            operations = get_operations(self.token, self.account_id, from_date, to_date)

            if self.figi:
                operations = [op for op in operations if op.figi == self.figi]

            print(f"[HistoryLoader] Получено операций: {len(operations)}")

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
    loaded = QtCore.pyqtSignal(object)
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
    """Вкладка реального счёта с торговой панелью."""

    def __init__(
            self,
            instruments_controller=None,
            quotes_hub: "QuotesHub" = None,
            app_context: AppContext = None,
            parent=None,
    ):
        super().__init__(parent)
        self.instruments_controller = instruments_controller
        self.quotes_hub = quotes_hub
        self.app_context = app_context

        if self.app_context:
            self.app_context.quotes_updated.connect(self._on_quotes_updated)

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

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Верхняя панель: информация о счёте + кнопка обновления + баланс
        top_panel = QtWidgets.QWidget()
        top_layout = QtWidgets.QHBoxLayout(top_panel)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(15)

        self.lbl_account_info = QtWidgets.QLabel("Загрузка...")
        self.lbl_account_info.setStyleSheet("font-weight: bold; font-size: 12px;")
        top_layout.addWidget(self.lbl_account_info, 1)

        separator = QtWidgets.QLabel("│")
        separator.setStyleSheet("color: #999; font-size: 12px;")
        top_layout.addWidget(separator)

        self.btn_refresh = QtWidgets.QPushButton("🔄 Обновить данные счёта")
        self.btn_refresh.setMinimumHeight(26)
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
        self.btn_refresh.clicked.connect(self._refresh_account)
        top_layout.addWidget(self.btn_refresh)

        separator2 = QtWidgets.QLabel("│")
        separator2.setStyleSheet("color: #999; font-size: 12px;")
        top_layout.addWidget(separator2)

        balance_widget = QtWidgets.QWidget()
        balance_layout = QtWidgets.QHBoxLayout(balance_widget)
        balance_layout.setContentsMargins(0, 0, 0, 0)
        balance_layout.setSpacing(12)

        self.lbl_total = QtWidgets.QLabel("**Всего:** -")
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

        # Сплиттер: избранное + торговая панель слева, история справа
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)

        # Левая панель - избранное + торговая панель
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # Заголовок + кнопка обновления
        left_header_layout = QtWidgets.QHBoxLayout()
        left_header_layout.setSpacing(4)
        left_header = QtWidgets.QLabel("📌 Избранное")
        left_header.setStyleSheet("font-weight: bold; font-size: 11px; padding: 4px;")
        left_header_layout.addWidget(left_header)
        left_header_layout.addStretch()

        self.btn_refresh_prices = QtWidgets.QPushButton("💹 Обновить цены")
        self.btn_refresh_prices.setMinimumHeight(22)
        self.btn_refresh_prices.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 9px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.btn_refresh_prices.clicked.connect(self._on_refresh_prices_clicked)
        left_header_layout.addWidget(self.btn_refresh_prices)
        left_layout.addLayout(left_header_layout)

        self.fav_table = QtWidgets.QTableWidget(0, 4)
        self.fav_table.setHorizontalHeaderLabels(["Инструмент", "Кол-во", "Цена", "Стоимость"])
        self.fav_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fav_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.fav_table.verticalHeader().setVisible(False)
        self.fav_table.setAlternatingRowColors(True)

        header = self.fav_table.horizontalHeader()
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(self.fav_table)

        # ===== ТОРГОВАЯ ПАНЕЛЬ =====
        # Заголовок "Торговля"
        trading_header = QtWidgets.QLabel("📈 Торговля")
        trading_header.setStyleSheet(
            "font-weight: bold; font-size: 12px; padding: 4px; background: #e3f2fd; border-radius: 3px;")
        left_layout.addWidget(trading_header)

        # Информация об инструменте
        self.trading_instrument_label = QtWidgets.QLabel("Инструмент: не выбран")
        self.trading_instrument_label.setStyleSheet("font-size: 10px; color: #666; padding: 4px;")
        self.trading_instrument_label.setWordWrap(True)
        left_layout.addWidget(self.trading_instrument_label)

        # Панель управления: лоты и цена в одну строку
        trading_params_layout = QtWidgets.QHBoxLayout()
        trading_params_layout.setSpacing(4)

        trading_params_layout.addWidget(QtWidgets.QLabel("Лотов:"))
        self.trading_lots_input = QtWidgets.QLineEdit("1")
        self.trading_lots_input.setMaximumWidth(60)
        self.trading_lots_input.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.trading_lots_input.setValidator(QtGui.QIntValidator(1, 999999))
        trading_params_layout.addWidget(self.trading_lots_input)

        trading_params_layout.addWidget(QtWidgets.QLabel("Цена:"))
        self.trading_price_input = QtWidgets.QLineEdit("")
        self.trading_price_input.setMaximumWidth(100)
        self.trading_price_input.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        price_validator = QtGui.QDoubleValidator(0.01, 999999.99, 2)
        self.trading_price_input.setValidator(price_validator)
        trading_params_layout.addWidget(self.trading_price_input)

        trading_params_layout.addStretch()
        left_layout.addLayout(trading_params_layout)

        # Кнопки BUY/SELL в одну строку
        trading_buttons_layout = QtWidgets.QHBoxLayout()
        trading_buttons_layout.setSpacing(4)

        self.btn_buy_limit = QtWidgets.QPushButton("🟢 BUY LIMIT")
        self.btn_buy_limit.setMinimumHeight(30)
        self.btn_buy_limit.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        self.btn_buy_limit.clicked.connect(self._on_buy_clicked_from_panel)
        trading_buttons_layout.addWidget(self.btn_buy_limit)

        self.btn_sell_limit = QtWidgets.QPushButton("🔴 SELL LIMIT")
        self.btn_sell_limit.setMinimumHeight(30)
        self.btn_sell_limit.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        self.btn_sell_limit.clicked.connect(self._on_sell_clicked_from_panel)
        trading_buttons_layout.addWidget(self.btn_sell_limit)

        left_layout.addLayout(trading_buttons_layout)

        # Результат операции (копируемый текст)
        self.trading_result_text = QtWidgets.QTextEdit("")
        self.trading_result_text.setMaximumHeight(60)
        self.trading_result_text.setReadOnly(True)
        self.trading_result_text.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse |
            QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.trading_result_text.setStyleSheet("""
            QTextEdit {
                font-size: 10px;
                padding: 4px;
                border: 1px solid #ddd;
                border-radius: 3px;
                background-color: #f9f9f9;
            }
        """)
        self.trading_result_text.setToolTip("Текст можно выделить и скопировать (Ctrl+C)")
        left_layout.addWidget(self.trading_result_text)

        # ===== Правая панель - заявки и история сделок =====
        orders_widget = QtWidgets.QWidget()
        orders_layout = QtWidgets.QVBoxLayout(orders_widget)
        orders_layout.setContentsMargins(0, 0, 0, 0)
        orders_layout.setSpacing(2)

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

        self.orders_table = QtWidgets.QTableWidget(0, 7)
        self.orders_table.setHorizontalHeaderLabels(["Дата", "Тип", "Ticker", "Статус", "Кол-во", "Цена", "Исполнено"])
        self.orders_table.horizontalHeader().setStretchLastSection(True)
        self.orders_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.orders_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.orders_table.verticalHeader().setVisible(False)
        self.orders_table.setAlternatingRowColors(True)
        orders_layout.addWidget(self.orders_table)

        history_widget = QtWidgets.QWidget()
        history_layout = QtWidgets.QVBoxLayout(history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(2)

        history_header_layout = QtWidgets.QHBoxLayout()
        history_header = QtWidgets.QLabel("📊 История сделок")
        history_header.setStyleSheet("font-weight: bold; font-size: 11px; padding: 4px;")
        history_header_layout.addWidget(history_header)
        history_header_layout.addStretch()

        self.btn_clear_cache = QtWidgets.QPushButton("🗑 Очистить кэш")
        self.btn_clear_cache.setMinimumHeight(22)
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

        self.history_table = QtWidgets.QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(["Дата", "Тип", "Ticker", "Кол-во", "Цена", "Сумма", "Валюта"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        history_layout.addWidget(self.history_table)

        right_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        right_splitter.addWidget(orders_widget)
        right_splitter.addWidget(history_widget)
        right_splitter.setHandleWidth(6)
        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 2)
        right_splitter.setSizes([200, 400])

        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        filter_panel = QtWidgets.QWidget()
        filter_panel.setStyleSheet("background: #e8f5e9; padding: 4px; border-radius: 3px;")
        filter_layout = QtWidgets.QHBoxLayout(filter_panel)
        filter_layout.setContentsMargins(4, 2, 4, 2)

        self.lbl_filter = QtWidgets.QLabel("Выберите инструмент в таблице слева")
        self.lbl_filter.setStyleSheet("color: #2e7d32; font-size: 10px; font-weight: bold;")
        filter_layout.addWidget(self.lbl_filter, 1)

        self.chk_filter_enabled = QtWidgets.QCheckBox("только выбранное")
        self.chk_filter_enabled.setChecked(True)
        self.chk_filter_enabled.setStyleSheet("font-size: 10px; font-weight: bold;")
        self.chk_filter_enabled.stateChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.chk_filter_enabled)
        right_layout.addWidget(filter_panel)
        right_layout.addWidget(right_splitter, 1)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([280, 720])
        main_layout.addWidget(splitter, 1)

        # Статус бар внизу
        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setStyleSheet("color: #666; font-size: 10px;")
        main_layout.addWidget(self.lbl_status)

        self.fav_table.cellClicked.connect(self._on_fav_selected)

        self._favorites = load_favorites(FAVORITES_FILE)
        self._refresh_account()

    def _refresh_account(self):
        """Обновить данные счёта."""
        if hasattr(self, '_account_thread') and self._account_thread and self._account_thread.isRunning():
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
            self.lbl_account_info.setText(f"💼 {self._account_info.account_id} ({self._account_info.account_type})")

            if self.app_context:
                self.app_context.real_account_id = self._account_info.account_id
                self.app_context.update_portfolio(self._portfolio_positions)
                print(f"[RealAccountTab] Saved real_account_id and {len(self._portfolio_positions)} positions")

        if portfolio:
            self._portfolio_positions = portfolio.positions
            total = portfolio.total_amount_portfolio
            self.lbl_total.setText(f"**Всего:** {total:,.2f} ₽")
            self.lbl_shares.setText(f"Акции: {portfolio.total_amount_shares:,.0f} ₽")
            self.lbl_bonds.setText(f"Обл: {portfolio.total_amount_bonds:,.0f} ₽")
            self.lbl_etf.setText(f"ETF: {portfolio.total_amount_etf:,.0f} ₽")
            self.lbl_currencies.setText(f"Валюта: {portfolio.total_amount_currencies:,.0f} ₽")
            self._update_favorites_table()

    def _on_account_finished(self):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔄 Обновить данные счёта")
        self._account_thread = None
        self._account_worker = None

    def _update_favorites_table(self):
        """Обновить таблицу избранного."""
        self.fav_table.setRowCount(0)
        positions_by_figi = {pos.figi: pos for pos in self._portfolio_positions}

        for info in self._favorites.values():
            r = self.fav_table.rowCount()
            self.fav_table.insertRow(r)

            pos = positions_by_figi.get(info.figi)
            qty = pos.quantity if pos else 0.0

            current_price = 0.0
            if self.app_context and info.figi:
                current_price = self.app_context.get_quote(info.figi) or 0.0
            if not current_price and pos:
                current_price = pos.current_price or pos.position_avg_price or 0.0

            value = qty * current_price if current_price else 0.0

            instrument_widget = QtWidgets.QWidget()
            instrument_widget.setToolTip(f"{info.ticker}\n{info.name or ''}")
            instrument_layout = QtWidgets.QVBoxLayout(instrument_widget)
            instrument_layout.setContentsMargins(4, 2, 4, 2)
            instrument_layout.setSpacing(0)

            ticker_label = QtWidgets.QLabel(info.ticker)
            ticker_label.setStyleSheet("font-weight: bold; color: #1976d2; font-size: 11px;")
            instrument_layout.addWidget(ticker_label)

            name_label = QtWidgets.QLabel(info.name or "-")
            name_label.setStyleSheet("color: #666; font-size: 10px;")
            instrument_layout.addWidget(name_label)

            instrument_widget.mousePressEvent = lambda e, row=r: self._on_fav_widget_clicked(row)
            ticker_label.mousePressEvent = lambda e, row=r: self._on_fav_widget_clicked(row)
            name_label.mousePressEvent = lambda e, row=r: self._on_fav_widget_clicked(row)

            self.fav_table.setCellWidget(r, 0, instrument_widget)

            qty_item = QtWidgets.QTableWidgetItem(f"{qty:,.6f}")
            qty_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.fav_table.setItem(r, 1, qty_item)

            price_item = QtWidgets.QTableWidgetItem(f"{current_price:,.2f}" if current_price else "-")
            price_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.fav_table.setItem(r, 2, price_item)

            value_item = QtWidgets.QTableWidgetItem(f"{value:,.2f} ₽" if value else "-")
            value_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            value_item.setForeground(QtGui.QColor("#2e7d32"))
            self.fav_table.setItem(r, 3, value_item)

    def _on_fav_widget_clicked(self, row: int):
        """Обработка клика по виджету инструмента."""
        self._on_fav_selected(row, 0)

    def _on_refresh_prices_clicked(self):
        """Обновить цены вручную."""
        if self.quotes_hub:
            self.quotes_hub.request_refresh()

    def _on_quotes_updated(self, quotes: dict):
        """Обновление котировок из контекста."""
        self._update_favorites_table()
        # Цена в торговой панели НЕ обновляется автоматически
        # Обновляется только при клике на инструменте

    def _on_fav_selected(self, row: int, column: int):
        """При выборе инструмента в избранном."""
        if row < 0 or row >= self.fav_table.rowCount():
            return

        instrument_widget = self.fav_table.cellWidget(row, 0)
        if not instrument_widget:
            return

        layout = instrument_widget.layout()
        if layout and layout.count() > 0:
            ticker_label = layout.itemAt(0).widget()
            if ticker_label:
                ticker = ticker_label.text()
                info = None
                for fav_info in self._favorites.values():
                    if fav_info.ticker == ticker:
                        info = fav_info
                        break

                if not info:
                    self.lbl_filter.setText(f"Инструмент {ticker} не найден в избранном")
                    return

                self._current_figi = info.figi
                current_price = self.app_context.get_quote(info.figi) if self.app_context else 0.0
                if not current_price:
                    positions_by_figi = {pos.figi: pos for pos in self._portfolio_positions}
                    pos = positions_by_figi.get(info.figi)
                    if pos:
                        current_price = pos.current_price or pos.position_avg_price or 0.0

                # Устанавливаем цену в торговую панель
                self.trading_price_input.setText(f"{current_price:.2f}" if current_price else "")

                # Устанавливаем информацию об инструменте
                self.trading_instrument_label.setText(f"Инструмент: {info.ticker} | {info.name or '-'}")

                # Очищаем результат
                self.trading_result_text.setText("")

                filter_state = "включен" if self.chk_filter_enabled.isChecked() else "выключен"
                self.lbl_filter.setText(f"📈 {info.ticker} | {info.name} (фильтр: {filter_state})")

                if self._all_orders:
                    self._on_orders_loaded(self._all_orders)
                self._load_history_from_cache(info.figi)

    def _load_history(self, figi: str):
        """Загрузить историю операций для инструмента."""
        if not self._account_info:
            self.lbl_filter.setText("Сначала загрузите данные счёта")
            return

        if hasattr(self, '_history_thread') and self._history_thread and self._history_thread.isRunning():
            return

        self.history_table.setRowCount(0)
        self.lbl_status.setText(f"⏳ Загрузка истории для {figi}...")

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
        """Загрузить историю из кэша."""
        if not self._account_info:
            return

        operations = load_operations_from_cache(self._account_info.account_id, figi)
        if operations:
            print(f"[RealAccountTab] Загружено из кэша: {len(operations)} операций")
            self._on_history_loaded(operations)
            self.lbl_status.setText(f"📚 Из кэша: {len(operations)} операций")
        else:
            self.history_table.setRowCount(0)
            self.lbl_status.setText(f"📚 Кэш пуст для {figi}. Нажмите 'Обновить'.")

    def _on_history_thread_finished(self):
        self._history_thread = None
        self._history_worker = None

    def _on_history_loaded(self, operations: list[Operation]):
        """Обработка загруженной истории."""
        self._current_operations = operations
        self.history_table.setRowCount(0)

        if self._current_figi and self.chk_filter_enabled.isChecked():
            operations = [op for op in operations if op.figi == self._current_figi]

        for op in operations:
            r = self.history_table.rowCount()
            self.history_table.insertRow(r)

            date_str = op.date.strftime("%Y-%m-%d %H:%M") if hasattr(op.date, "strftime") else str(op.date)
            self.history_table.setItem(r, 0, QtWidgets.QTableWidgetItem(date_str))

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
            elif "dividend" in op_type_lower:
                type_item.setForeground(QtGui.QColor("#2196F3"))
            elif "commission" in op_type_lower:
                type_item.setForeground(QtGui.QColor("#ff9800"))
            self.history_table.setItem(r, 1, type_item)

            self.history_table.setItem(r, 2, QtWidgets.QTableWidgetItem(op.ticker or "-"))

            qty_item = QtWidgets.QTableWidgetItem(f"{op.quantity:,.6f}")
            qty_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(r, 3, qty_item)

            price_item = QtWidgets.QTableWidgetItem(f"{op.price:,.2f}")
            price_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(r, 4, price_item)

            amount_item = QtWidgets.QTableWidgetItem(f"{op.amount:,.2f}")
            amount_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(r, 5, amount_item)

            self.history_table.setItem(r, 6, QtWidgets.QTableWidgetItem(op.currency))

        self.lbl_status.setText(f"✅ Загружено операций: {len(operations)}")

    def _on_history_error(self, error: str):
        self.lbl_status.setText(f"❌ Ошибка: {error[:50]}...")
        print(f"[RealAccountTab] History error: {error}")

    def _refresh_history_for_selected(self):
        if self._current_figi:
            self._load_history(self._current_figi)
        else:
            self.lbl_filter.setText("Сначала выберите инструмент в таблице слева")

    def _clear_cache_and_reload(self):
        from core.operations_api import clear_history_cache
        clear_history_cache()
        if self._current_figi:
            self.lbl_status.setText("🗑 Кэш очищен, загружаем заново...")
            self._load_history(self._current_figi)
        QtWidgets.QMessageBox.information(self, "Кэш", "Кэш очищен.")

    def _refresh_orders(self):
        """Обновить заявки."""
        if not self._account_info:
            self.lbl_orders_status.setText("Сначала загрузите данные счёта")
            return

        if self._orders_thread and self._orders_thread.isRunning():
            return

        self.btn_refresh_orders.setEnabled(False)
        self.lbl_orders_status.setText("⏳ Загрузка заявок...")

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
        if self._all_orders:
            self._on_orders_loaded(self._all_orders)
        if hasattr(self, '_current_operations') and self._current_operations:
            self._on_history_loaded(self._current_operations)

    def _on_orders_loaded(self, orders: list[Order]):
        """Обработка загруженных заявок."""
        self._all_orders = orders
        self.orders_table.setRowCount(0)

        if self._current_figi and self.chk_filter_enabled.isChecked():
            orders = [o for o in orders if o.figi == self._current_figi]

        if self._current_figi:
            self.lbl_orders_status.setText(f"📈 {self._current_figi}: {len(orders)} заявок")
        else:
            self.lbl_orders_status.setText(f"✅ Заявок: {len(orders)}")

        for order in orders:
            r = self.orders_table.rowCount()
            self.orders_table.insertRow(r)

            date_str = order.updated.strftime("%Y-%m-%d %H:%M") if order.updated else (
                order.created.strftime("%Y-%m-%d %H:%M") if order.created else "-")
            self.orders_table.setItem(r, 0, QtWidgets.QTableWidgetItem(date_str))

            order_type = order.order_type if order.order_type else ""
            type_item = QtWidgets.QTableWidgetItem(order_type)
            if "BUY" in order_type:
                type_item.setForeground(QtGui.QColor("#4CAF50"))
            elif "SELL" in order_type:
                type_item.setForeground(QtGui.QColor("#f44336"))
            self.orders_table.setItem(r, 1, type_item)

            self.orders_table.setItem(r, 2, QtWidgets.QTableWidgetItem(order.ticker or "-"))

            status_item = QtWidgets.QTableWidgetItem(order.status)
            if "filled" in order.status.lower():
                status_item.setForeground(QtGui.QColor("#4CAF50"))
            elif "cancelled" in order.status.lower():
                status_item.setForeground(QtGui.QColor("#999"))
            self.orders_table.setItem(r, 3, status_item)

            qty_item = QtWidgets.QTableWidgetItem(f"{order.lots_requested:,.0f}")
            qty_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.orders_table.setItem(r, 4, qty_item)

            price_item = QtWidgets.QTableWidgetItem(f"{order.price:,.2f}")
            price_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.orders_table.setItem(r, 5, price_item)

            exec_item = QtWidgets.QTableWidgetItem(f"{order.lots_executed:,.0f}")
            exec_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.orders_table.setItem(r, 6, exec_item)

        self.lbl_orders_status.setText(f"✅ Заявок: {len(orders)}")

    def _on_orders_error(self, error: str):
        self.lbl_orders_status.setText(f"❌ Ошибка: {error[:50]}...")
        print(f"[RealAccountTab] Orders error: {error}")

    def _on_orders_finished(self):
        self.btn_refresh_orders.setEnabled(True)
        self._orders_thread = None
        self._orders_worker = None

    def _on_error(self, error: str):
        """Обработка ошибки."""
        self._show_error_in_text_box(error)

    def _show_error_in_text_box(self, error: str):
        """Показать ошибку в текстовом поле."""
        layout = self.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(self)
            self.setLayout(layout)

        error_header = QtWidgets.QLabel("❌ Ошибка загрузки реального счёта:")
        error_header.setStyleSheet("font-weight: bold; font-size: 14px; color: red;")
        layout.insertWidget(0, error_header)

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

        copy_btn = QtWidgets.QPushButton("📋 Копировать ошибку")
        copy_btn.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(error_text.toPlainText()))
        layout.insertWidget(2, copy_btn)

        print("\n" + "=" * 60)
        print("ОШИБКА РЕАЛЬНОГО СЧЁТА:")
        print("=" * 60)
        print(error)
        print("=" * 60 + "\n")

    def _on_buy_clicked_from_panel(self):
        """Обработка клика кнопки BUY."""
        if not self._current_figi:
            self.trading_result_text.setText("❌ Выберите инструмент")
            return

        try:
            lots = int(self.trading_lots_input.text().strip())
            price = float(self.trading_price_input.text().strip().replace(",", "."))

            if lots <= 0 or price <= 0:
                raise ValueError()

            info = None
            for fav_info in self._favorites.values():
                if fav_info.figi == self._current_figi:
                    info = fav_info
                    break

            if not info:
                self.trading_result_text.setText("❌ Инструмент не найден")
                return

            self._execute_buy_order(info, lots, price)
        except ValueError:
            self.trading_result_text.setText("❌ Проверьте значения лотов и цены")

    def _on_sell_clicked_from_panel(self):
        """Обработка клика кнопки SELL."""
        if not self._current_figi:
            self.trading_result_text.setText("❌ Выберите инструмент")
            return

        try:
            lots = int(self.trading_lots_input.text().strip())
            price = float(self.trading_price_input.text().strip().replace(",", "."))

            if lots <= 0 or price <= 0:
                raise ValueError()

            info = None
            for fav_info in self._favorites.values():
                if fav_info.figi == self._current_figi:
                    info = fav_info
                    break

            if not info:
                self.trading_result_text.setText("❌ Инструмент не найден")
                return

            self._execute_sell_order(info, lots, price)
        except ValueError:
            self.trading_result_text.setText("❌ Проверьте значения лотов и цены")

    def _execute_buy_order(self, instrument: InstrumentInfo, lots: int, price: float):
        """Выставить заявку на покупку."""
        if not self.app_context:
            self.trading_result_text.setText("❌ Нет контекста приложения")
            return

        account_id = self.app_context.real_account_id
        if not REAL_TOKEN or not account_id:
            self.trading_result_text.setText("❌ Нет токена или account_id")
            return

        self.trading_result_text.setText(f"⏳ Выставление заявки на покупку {lots} лотов по {price:.2f}...")
        self.trading_result_text.setStyleSheet("color: #1976d2;")

        result = post_order(
            token=REAL_TOKEN,
            account_id=account_id,
            figi=instrument.figi,
            quantity=lots,
            price=price,
            direction="buy",
        )

        if result.success:
            self.trading_result_text.setText(f"✅ Заявка {result.order_id} выставлена")
            self.trading_result_text.setStyleSheet("color: #4CAF50;")
            self._refresh_orders()
        else:
            error_msg = result.error or result.message or "Неизвестная ошибка"
            self.trading_result_text.setText(f"❌ Ошибка: {error_msg}")
            self.trading_result_text.setStyleSheet("color: #f44336;")

    def _execute_sell_order(self, instrument: InstrumentInfo, lots: int, price: float):
        """Выставить заявку на продажу."""
        if not self.app_context:
            self.trading_result_text.setText("❌ Нет контекста приложения")
            return

        account_id = self.app_context.real_account_id
        if not REAL_TOKEN or not account_id:
            self.trading_result_text.setText("❌ Нет токена или account_id")
            return

        self.trading_result_text.setText(f"⏳ Выставление заявки на продажу {lots} лотов по {price:.2f}...")
        self.trading_result_text.setStyleSheet("color: #ff9800;")

        result = post_order(
            token=REAL_TOKEN,
            account_id=account_id,
            figi=instrument.figi,
            quantity=lots,
            price=price,
            direction="sell",
        )

        if result.success:
            self.trading_result_text.setText(f"✅ Заявка {result.order_id} выставлена")
            self.trading_result_text.setStyleSheet("color: #4CAF50;")
            self._refresh_orders()
        else:
            error_msg = result.error or result.message or "Неизвестная ошибка"
            self.trading_result_text.setText(f"❌ Ошибка: {error_msg}")
            self.trading_result_text.setStyleSheet("color: #f44336;")