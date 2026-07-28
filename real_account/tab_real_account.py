# real_account/tab_real_account.py
"""
Вкладка "Реальный счёт" - информация по реальному счёту с торговой панелью.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PyQt6 import QtCore, QtGui, QtWidgets

from app.config import REAL_TOKEN, REAL_TOKEN_ERROR, REAL_TOKEN_FILE, FAVORITES_FILE
from app.app_context import AppContext
from core.account_api import get_accounts, get_portfolio, PortfolioPosition, AccountInfo
from core.operations_api import load_operations_from_cache, Operation, clear_history_cache
from core.orders_api import Order
from core.instruments_catalog import InstrumentInfo
from core.favorites_repo import load_favorites
from core.trading_api import post_order
from real_account.plan_models import PlanOrder
from real_account.plan_controller import PlanController
from real_account.ra_workers import RealAccountLoader, HistoryLoader, OrdersLoader

if TYPE_CHECKING:
    from market_data.quotes_hub import QuotesHub


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

        # Контроллер плана
        self.plan_controller: Optional[PlanController] = None

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

        # Верхняя панель
        top_panel = QtWidgets.QWidget()
        top_layout = QtWidgets.QHBoxLayout(top_panel)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(15)

        self.lbl_account_info = QtWidgets.QLabel("Загрузка...")
        top_layout.addWidget(self.lbl_account_info, 1)

        separator = QtWidgets.QLabel("│")
        top_layout.addWidget(separator)

        self.btn_refresh = QtWidgets.QPushButton("🔄 Обновить данные счёта")
        self.btn_refresh.setMinimumHeight(26)
        self.btn_refresh.clicked.connect(self._refresh_account)
        top_layout.addWidget(self.btn_refresh)

        separator2 = QtWidgets.QLabel("│")
        top_layout.addWidget(separator2)

        balance_widget = QtWidgets.QWidget()
        balance_layout = QtWidgets.QHBoxLayout(balance_widget)
        balance_layout.setContentsMargins(0, 0, 0, 0)
        balance_layout.setSpacing(12)

        self.lbl_total = QtWidgets.QLabel("**Всего:** -")
        balance_layout.addWidget(self.lbl_total)

        self.lbl_shares = QtWidgets.QLabel("Акции: -")
        balance_layout.addWidget(self.lbl_shares)

        self.lbl_bonds = QtWidgets.QLabel("Обл: -")
        balance_layout.addWidget(self.lbl_bonds)

        self.lbl_etf = QtWidgets.QLabel("ETF: -")
        balance_layout.addWidget(self.lbl_etf)

        self.lbl_currencies = QtWidgets.QLabel("Валюта: -")
        balance_layout.addWidget(self.lbl_currencies)

        balance_layout.addStretch()
        top_layout.addWidget(balance_widget)
        main_layout.addWidget(top_panel)

        # Сплиттер
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)

        # Левая панель
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        left_header_layout = QtWidgets.QHBoxLayout()
        left_header = QtWidgets.QLabel("📌 Избранное")
        left_header_layout.addWidget(left_header)
        left_header_layout.addStretch()

        self.btn_refresh_prices = QtWidgets.QPushButton("💹 Обновить цены")
        self.btn_refresh_prices.setMinimumHeight(22)
        self.btn_refresh_prices.clicked.connect(self._on_refresh_prices_clicked)
        left_header_layout.addWidget(self.btn_refresh_prices)
        left_layout.addLayout(left_header_layout)

        self.fav_table = QtWidgets.QTableWidget(0, 4)
        self.fav_table.setHorizontalHeaderLabels(["Инструмент", "Кол-во", "Цена", "Стоимость"])
        self.fav_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fav_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.fav_table.verticalHeader().setVisible(False)
        self.fav_table.setAlternatingRowColors(True)
        self.fav_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(self.fav_table)

        # Торговая панель
        trading_header = QtWidgets.QLabel("📈 Торговля")
        left_layout.addWidget(trading_header)

        self.trading_instrument_label = QtWidgets.QLabel("Инструмент: не выбран")
        self.trading_instrument_label.setWordWrap(True)
        left_layout.addWidget(self.trading_instrument_label)

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
        self.trading_price_input.setValidator(QtGui.QDoubleValidator(0.01, 999999.99, 2))
        trading_params_layout.addWidget(self.trading_price_input)
        trading_params_layout.addStretch()
        left_layout.addLayout(trading_params_layout)

        trading_buttons_layout = QtWidgets.QHBoxLayout()
        trading_buttons_layout.setSpacing(4)

        self.btn_buy_limit = QtWidgets.QPushButton("🟢 BUY LIMIT")
        self.btn_buy_limit.setMinimumHeight(30)
        self.btn_buy_limit.clicked.connect(self._on_buy_clicked_from_panel)
        trading_buttons_layout.addWidget(self.btn_buy_limit)

        self.btn_sell_limit = QtWidgets.QPushButton("🔴 SELL LIMIT")
        self.btn_sell_limit.setMinimumHeight(30)
        self.btn_sell_limit.clicked.connect(self._on_sell_clicked_from_panel)
        trading_buttons_layout.addWidget(self.btn_sell_limit)
        left_layout.addLayout(trading_buttons_layout)

        self.trading_result_text = QtWidgets.QTextEdit("")
        self.trading_result_text.setMaximumHeight(60)
        self.trading_result_text.setReadOnly(True)
        self.trading_result_text.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse |
            QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        left_layout.addWidget(self.trading_result_text)

        # Правая панель
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        filter_panel = QtWidgets.QWidget()
        filter_layout = QtWidgets.QHBoxLayout(filter_panel)
        filter_layout.setContentsMargins(4, 2, 4, 2)

        self.lbl_filter = QtWidgets.QLabel("Выберите инструмент в таблице слева")
        filter_layout.addWidget(self.lbl_filter, 1)

        self.chk_filter_enabled = QtWidgets.QCheckBox("только выбранное")
        self.chk_filter_enabled.setChecked(True)
        self.chk_filter_enabled.stateChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.chk_filter_enabled)
        right_layout.addWidget(filter_panel)

        # План заявок (без рамки, как у других таблиц)
        plan_header_layout = QtWidgets.QHBoxLayout()
        plan_header = QtWidgets.QLabel("📋 План заявок")
        plan_header_layout.addWidget(plan_header)
        plan_header_layout.addStretch()
        right_layout.addLayout(plan_header_layout)

        self.plan_table = QtWidgets.QTableWidget(0, 7)
        self.plan_table.setHorizontalHeaderLabels(
            ["Инструмент", "Направление", "Кол-во", "Цена", "Тип", "Статус", "Действие"])
        self.plan_table.horizontalHeader().setStretchLastSection(False)
        self.plan_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.plan_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.setMinimumHeight(100)
        self.plan_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.plan_table.verticalHeader().setVisible(False)
        self.plan_table.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)

        # Инициализация контроллера плана
        self.plan_controller = PlanController(
            plan_table=self.plan_table,
            get_account_info=lambda: self._account_info,
            on_refresh_orders=self._refresh_orders,
            token=REAL_TOKEN,
        )

        # Активные заявки
        orders_widget = QtWidgets.QWidget()
        orders_widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        orders_layout = QtWidgets.QVBoxLayout(orders_widget)
        orders_layout.setContentsMargins(0, 0, 0, 0)
        orders_layout.setSpacing(2)

        orders_header_layout = QtWidgets.QHBoxLayout()
        orders_header = QtWidgets.QLabel("📋 Активные заявки")
        orders_header_layout.addWidget(orders_header)

        self.btn_refresh_orders = QtWidgets.QPushButton("🔄 Обновить")
        self.btn_refresh_orders.setMinimumHeight(22)
        self.btn_refresh_orders.clicked.connect(self._refresh_orders)
        orders_header_layout.addWidget(self.btn_refresh_orders)

        self.lbl_orders_status = QtWidgets.QLabel("Заявок: 0")
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

        # Сплиттер между Планом и Заявками
        top_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        top_splitter.addWidget(self.plan_table)
        top_splitter.addWidget(orders_widget)
        top_splitter.setChildrenCollapsible(False)
        top_splitter.setHandleWidth(6)
        top_splitter.setCollapsible(0, False)
        top_splitter.setCollapsible(1, False)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setSizes([150, 200])

        history_widget = QtWidgets.QWidget()
        history_layout = QtWidgets.QVBoxLayout(history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(2)

        history_header_layout = QtWidgets.QHBoxLayout()
        history_header = QtWidgets.QLabel("📊 История сделок")
        history_header_layout.addWidget(history_header)
        history_header_layout.addStretch()

        self.btn_clear_cache = QtWidgets.QPushButton("🗑 Очистить кэш")
        self.btn_clear_cache.setMinimumHeight(22)
        self.btn_clear_cache.clicked.connect(self._clear_cache_and_reload)
        history_header_layout.addWidget(self.btn_clear_cache)

        self.btn_refresh_history = QtWidgets.QPushButton("🔄 Обновить")
        self.btn_refresh_history.setMinimumHeight(22)
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
        right_splitter.addWidget(top_splitter)
        right_splitter.addWidget(history_widget)
        right_splitter.setChildrenCollapsible(False)
        right_splitter.setHandleWidth(6)
        right_splitter.setCollapsible(0, False)
        right_splitter.setCollapsible(1, False)
        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 1)
        right_splitter.setSizes([350, 200])

        right_layout.addWidget(right_splitter, 1)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([280, 720])
        main_layout.addWidget(splitter, 1)

        self.lbl_status = QtWidgets.QLabel("")
        main_layout.addWidget(self.lbl_status)

        self.fav_table.cellClicked.connect(self._on_fav_selected)
        self._favorites = load_favorites(FAVORITES_FILE)
        self._refresh_account()

        # Загружаем план
        if self.plan_controller:
            self.plan_controller.load()

    # =========================================================================
    # Методы плана заявок (делегированы контроллеру)
    # =========================================================================

    def add_plan_order(self, order: PlanOrder) -> None:
        if self.plan_controller:
            self.plan_controller.add_order(order)

    def sync_plan_with_orders(self, orders: list[Order]) -> None:
        if self.plan_controller:
            self.plan_controller.sync_with_orders(orders)

    # =========================================================================
    # Счёт
    # =========================================================================

    def _refresh_account(self):
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
        self._account_info = data.get("account")
        portfolio = data.get("portfolio")

        if self._account_info:
            self.lbl_account_info.setText(f"💼 {self._account_info.account_id} ({self._account_info.account_type})")
            if self.app_context:
                self.app_context.real_account_id = self._account_info.account_id
                self.app_context.update_portfolio(self._portfolio_positions)

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

    # =========================================================================
    # Избранное
    # =========================================================================

    def _update_favorites_table(self):
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
            instrument_layout.addWidget(ticker_label)

            name_label = QtWidgets.QLabel(info.name or "-")
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
        self._on_fav_selected(row, 0)

    def _on_refresh_prices_clicked(self):
        if self.quotes_hub:
            self.quotes_hub.request_refresh()

    def _on_quotes_updated(self, quotes: dict):
        self._update_favorites_table()

    def _on_fav_selected(self, row: int, column: int):
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

                self.trading_price_input.setText(f"{current_price:.2f}" if current_price else "")
                self.trading_instrument_label.setText(f"Инструмент: {info.ticker} | {info.name or '-'}")
                self.trading_result_text.setText("")

                filter_state = "включен" if self.chk_filter_enabled.isChecked() else "выключен"
                self.lbl_filter.setText(f"📈 {info.ticker} | {info.name} (фильтр: {filter_state})")

                if self._all_orders:
                    self._on_orders_loaded(self._all_orders)
                self._load_history_from_cache(info.figi)

    # =========================================================================
    # История
    # =========================================================================

    def _load_history(self, figi: str):
        if not self._account_info:
            self.lbl_filter.setText("Сначала загрузите данные счёта")
            return

        if hasattr(self, '_history_thread') and self._history_thread and self._history_thread.isRunning():
            return

        self.history_table.setRowCount(0)
        self.lbl_status.setText(f"⏳ Загрузка истории для {figi}...")

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
            self.history_table.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{op.quantity:,.6f}"))
            self.history_table.setItem(r, 4, QtWidgets.QTableWidgetItem(f"{op.price:,.2f}"))
            self.history_table.setItem(r, 5, QtWidgets.QTableWidgetItem(f"{op.amount:,.2f}"))
            self.history_table.setItem(r, 6, QtWidgets.QTableWidgetItem(op.currency))

        self.lbl_status.setText(f"✅ Загружено операций: {len(operations)}")

    def _on_history_error(self, error: str):
        self.lbl_status.setText(f"❌ Ошибка: {error[:50]}...")

    def _refresh_history_for_selected(self):
        if self._current_figi:
            self._load_history(self._current_figi)
        else:
            self.lbl_filter.setText("Сначала выберите инструмент в таблице слева")

    def _clear_cache_and_reload(self):
        clear_history_cache()
        if self._current_figi:
            self.lbl_status.setText("🗑 Кэш очищен, загружаем заново...")
            self._load_history(self._current_figi)
        QtWidgets.QMessageBox.information(self, "Кэш", "Кэш очищен.")

    # =========================================================================
    # Заявки
    # =========================================================================

    def _refresh_orders(self):
        if not self._account_info:
            self.lbl_orders_status.setText("Сначала загрузите данные счёта")
            return

        if self._orders_thread and self._orders_thread.isRunning():
            return

        self.btn_refresh_orders.setEnabled(False)
        self.lbl_orders_status.setText("⏳ Загрузка заявок...")

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
        if self._all_orders:
            self._on_orders_loaded(self._all_orders)
        if hasattr(self, '_current_operations') and self._current_operations:
            self._on_history_loaded(self._current_operations)

    def _on_orders_loaded(self, orders: list[Order]):
        self._all_orders = orders
        self.orders_table.setRowCount(0)

        if self._current_figi and self.chk_filter_enabled.isChecked():
            orders = [o for o in orders if o.figi == self._current_figi]

        self.lbl_orders_status.setText(
            f"📈 {self._current_figi}: {len(orders)} заявок" if self._current_figi else f"✅ Заявок: {len(orders)}")

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

            self.orders_table.setItem(r, 4, QtWidgets.QTableWidgetItem(f"{order.lots_requested:,.0f}"))
            self.orders_table.setItem(r, 5, QtWidgets.QTableWidgetItem(f"{order.price:,.2f}"))
            self.orders_table.setItem(r, 6, QtWidgets.QTableWidgetItem(f"{order.lots_executed:,.0f}"))

        self.lbl_orders_status.setText(f"✅ Заявок: {len(orders)}")
        self.sync_plan_with_orders(orders)

    def _on_orders_error(self, error: str):
        self.lbl_orders_status.setText(f"❌ Ошибка: {error[:50]}...")

    def _on_orders_finished(self):
        self.btn_refresh_orders.setEnabled(True)
        self._orders_thread = None
        self._orders_worker = None

    # =========================================================================
    # Ошибки
    # =========================================================================

    def _on_error(self, error: str):
        self._show_error_in_text_box(error)

    def _show_error_in_text_box(self, error: str):
        layout = self.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(self)
            self.setLayout(layout)

        error_header = QtWidgets.QLabel("❌ Ошибка загрузки реального счёта:")
        layout.insertWidget(0, error_header)

        error_text = QtWidgets.QTextEdit()
        error_text.setReadOnly(True)
        error_text.setPlainText(error)
        error_text.setMinimumHeight(300)
        layout.insertWidget(1, error_text)

        copy_btn = QtWidgets.QPushButton("📋 Копировать ошибку")
        copy_btn.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(error_text.toPlainText()))
        layout.insertWidget(2, copy_btn)

        print("\n" + "=" * 60 + "\nОШИБКА РЕАЛЬНОГО СЧЁТА:\n" + "=" * 60 + "\n" + error + "\n" + "=" * 60 + "\n")

    # =========================================================================
    # Торговля
    # =========================================================================

    def _on_buy_clicked_from_panel(self):
        if not self._current_figi:
            self.trading_result_text.setText("❌ Выберите инструмент")
            return

        try:
            lots = int(self.trading_lots_input.text().strip())
            price = float(self.trading_price_input.text().strip().replace(",", "."))
            if lots <= 0 or price <= 0:
                raise ValueError()

            info = next((f for f in self._favorites.values() if f.figi == self._current_figi), None)
            if not info:
                self.trading_result_text.setText("❌ Инструмент не найден")
                return

            self._execute_order(info, lots, price, "buy")
        except ValueError:
            self.trading_result_text.setText("❌ Проверьте значения лотов и цены")

    def _on_sell_clicked_from_panel(self):
        if not self._current_figi:
            self.trading_result_text.setText("❌ Выберите инструмент")
            return

        try:
            lots = int(self.trading_lots_input.text().strip())
            price = float(self.trading_price_input.text().strip().replace(",", "."))
            if lots <= 0 or price <= 0:
                raise ValueError()

            info = next((f for f in self._favorites.values() if f.figi == self._current_figi), None)
            if not info:
                self.trading_result_text.setText("❌ Инструмент не найден")
                return

            self._execute_order(info, lots, price, "sell")
        except ValueError:
            self.trading_result_text.setText("❌ Проверьте значения лотов и цены")

    def _execute_order(self, instrument: InstrumentInfo, lots: int, price: float, direction: str):
        if not self.app_context:
            self.trading_result_text.setText("❌ Нет контекста приложения")
            return

        account_id = self.app_context.real_account_id
        if not REAL_TOKEN or not account_id:
            self.trading_result_text.setText("❌ Нет токена или account_id")
            return

        # Создаём запись в плане
        plan_order = PlanOrder.create(
            figi=instrument.figi,
            ticker=instrument.ticker,
            quantity=lots,
            price=price,
            direction=direction,
            order_type="limit",
        )
        self.add_plan_order(plan_order)

        action = "покупку" if direction == "buy" else "продажу"
        self.trading_result_text.setText(f"⏳ Выставление заявки на {action} {lots} лотов по {price:.2f}...")

        result = post_order(
            token=REAL_TOKEN,
            account_id=account_id,
            figi=instrument.figi,
            quantity=lots,
            price=price,
            direction=direction,
        )

        if result.success:
            plan_order.mark_submitted(result.order_id)
            from real_account.plan_repo import update_plan_order
            update_plan_order(plan_order)
            self.trading_result_text.setText(f"✅ Заявка {result.order_id} выставлена")
            self._refresh_orders()
        else:
            plan_order.mark_rejected()
            from real_account.plan_repo import update_plan_order
            update_plan_order(plan_order)
            self.trading_result_text.setText(f"❌ Ошибка: {result.error or result.message}")