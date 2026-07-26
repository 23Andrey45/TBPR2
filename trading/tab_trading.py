# tabs/tab_trading.py
"""
Вкладка "Торговля" - торговля инструментами с реального счёта.
Аналогична вкладке "Реальный счёт" + торговая панель.
"""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from app.app_context import AppContext
from core.instruments_catalog import InstrumentInfo
from core.favorites_repo import load_favorites
from app.config import FAVORITES_FILE, REAL_TOKEN, REAL_TOKEN_ERROR, REAL_TOKEN_FILE
from trading.trading_panel_widget import TradingPanelWidget
from core.trading_api import post_order
from core.account_api import get_accounts, get_portfolio, PortfolioPosition, AccountInfo
from core.operations_api import get_operations, save_operations_to_cache, load_operations_from_cache, OPERATION_TYPE_MAP, clear_history_cache
from core.orders_api import get_orders
from datetime import datetime, timezone, timedelta


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
            print(f"[TradingTab] Начинаем загрузку...")
            accounts = get_accounts(self.token)
            print(f"[TradingTab] Получено счетов: {len(accounts)}")

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

            print(f"[TradingTab] Используем счёт: {account.account_id}")
            portfolio = get_portfolio(self.token, account.account_id)
            print(f"[TradingTab] Получено позиций: {len(portfolio.positions)}")

            self.loaded.emit({
                "account": account,
                "portfolio": portfolio,
            })
        except Exception as e:
            import traceback
            print(f"[TradingTab] Ошибка: {e}")
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()


class HistoryLoader(QtCore.QObject):
    """Загрузчик истории операций."""
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
            cached = load_operations_from_cache(self.account_id, self.figi)
            if cached:
                print(f"[HistoryLoader] Загружено из кэша: {len(cached)} операций")
                self.loaded.emit(cached)
                self.finished.emit()
                return

            to_date = datetime.now(timezone.utc)
            from_date = to_date - timedelta(days=self.days)

            operations = get_operations(self.token, self.account_id, from_date, to_date)
            if operations:
                save_operations_to_cache(self.account_id, self.figi, operations)

            self.loaded.emit(operations)
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()


class OrdersLoader(QtCore.QObject):
    """Загрузчик активных заявок."""
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
            orders = get_orders(self.token, self.account_id)
            print(f"[OrdersLoader] Получено активных заявок: {len(orders)}")
            self.loaded.emit(orders)
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()


class TradingTab(QtWidgets.QWidget):
    """Вкладка торговли (аналогична Реальный счёт + торговая панель)."""

    def __init__(self, app_context: AppContext = None, parent=None):
        super().__init__(parent)

        self.app_context = app_context

        self._account_thread: Optional[QtCore.QThread] = None
        self._account_worker: Optional[RealAccountLoader] = None
        self._history_thread: Optional[QtCore.QThread] = None
        self._history_worker: Optional[HistoryLoader] = None
        self._orders_thread: Optional[QtCore.QThread] = None
        self._orders_worker: Optional[OrdersLoader] = None

        self._portfolio_positions: list[PortfolioPosition] = []
        self._account_info: Optional[AccountInfo] = None
        self._current_figi: Optional[str] = None
        self._current_price: float = 0.0
        self._favorites: dict[str, InstrumentInfo] = {}
        self._all_orders: list = []
        self._current_operations: list = []

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

        # Загрузка избранного
        self._favorites = load_favorites(FAVORITES_FILE)

        # Основной layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Верхняя панель: информация о счёте + баланс
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

        # Сплиттер: избранное + торговая панель слева, история справа
        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        main_splitter.setHandleWidth(6)

        # Левая панель: избранное + торговая панель
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # Избранное
        fav_header_layout = QtWidgets.QHBoxLayout()
        fav_header_layout.setSpacing(4)

        fav_header = QtWidgets.QLabel("📌 Избранное")
        fav_header.setStyleSheet("font-weight: bold; font-size: 11px; padding: 4px;")
        fav_header_layout.addWidget(fav_header)
        fav_header_layout.addStretch()

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
        fav_header_layout.addWidget(self.btn_refresh_prices)

        left_layout.addLayout(fav_header_layout)

        self.fav_table = QtWidgets.QTableWidget(0, 4)
        self.fav_table.setHorizontalHeaderLabels(["Инструмент", "Кол-во", "Цена", "Стоимость"])
        self.fav_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fav_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.fav_table.verticalHeader().setVisible(False)
        self.fav_table.setAlternatingRowColors(True)
        header = self.fav_table.horizontalHeader()
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(self.fav_table)

        # Торговая панель
        self.trading_panel = TradingPanelWidget()
        self.trading_panel.buy_clicked.connect(self._on_buy_clicked)
        self.trading_panel.sell_clicked.connect(self._on_sell_clicked)
        left_layout.addWidget(self.trading_panel)

        main_splitter.addWidget(left_widget)

        # Правая панель: история сделок
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        history_header = QtWidgets.QLabel("📊 История сделок")
        history_header.setStyleSheet(
            "font-weight: bold; font-size: 11px; padding: 4px; background: #f5f5f5; border-radius: 3px;")
        right_layout.addWidget(history_header)

        history_filter_layout = QtWidgets.QHBoxLayout()
        self.lbl_filter = QtWidgets.QLabel("Выберите инструмент в таблице слева")
        self.lbl_filter.setStyleSheet("color: #666; font-size: 10px; font-style: italic;")
        history_filter_layout.addWidget(self.lbl_filter)
        history_filter_layout.addStretch()

        self.btn_clear_cache = QtWidgets.QPushButton("🗑 Очистить кэш")
        self.btn_clear_cache.setMinimumHeight(24)
        self.btn_clear_cache.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 3px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        self.btn_clear_cache.clicked.connect(self._clear_cache_and_reload)
        history_filter_layout.addWidget(self.btn_clear_cache)

        self.btn_refresh_history = QtWidgets.QPushButton("🔄 Обновить")
        self.btn_refresh_history.setMinimumHeight(24)
        self.btn_refresh_history.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 3px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.btn_refresh_history.clicked.connect(self._refresh_history_for_selected)
        history_filter_layout.addWidget(self.btn_refresh_history)

        right_layout.addLayout(history_filter_layout)

        self.history_table = QtWidgets.QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(["Дата", "Тип", "Ticker", "Кол-во", "Цена", "Сумма", "Валюта"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        right_layout.addWidget(self.history_table)

        main_splitter.addWidget(right_widget)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 2)
        main_splitter.setSizes([600, 400])

        main_layout.addWidget(main_splitter, 1)

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
        self.btn_refresh.clicked.connect(self._refresh_account)
        bottom_layout.addWidget(self.btn_refresh)
        bottom_layout.addStretch()

        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setStyleSheet("color: #666; font-size: 10px;")
        bottom_layout.addWidget(self.lbl_status)

        main_layout.addWidget(bottom_panel)

        # Подписка на обновления из контекста
        if self.app_context:
            self.app_context.quotes_updated.connect(self._on_quotes_updated)
            self.app_context.portfolio_updated.connect(self._on_portfolio_updated)

        # Автозагрузка
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
            self.lbl_account_info.setText(
                f"💼 {self._account_info.account_id} ({self._account_info.account_type})"
            )

            # Сохраняем в app_context
            try:
                ctx = self.app_context
                if ctx:
                    ctx.real_account_id = self._account_info.account_id
                    ctx.update_portfolio(self._portfolio_positions)
                    print(f"[TradingTab] Saved real_account_id and {len(self._portfolio_positions)} positions")
            except Exception as e:
                print(f"[TradingTab] Failed to save to context: {e}")

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

            # Инструмент (Ticker + Name)
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

            # Кол-во
            qty_item = QtWidgets.QTableWidgetItem(f"{qty:,.6f}")
            qty_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.fav_table.setItem(r, 1, qty_item)

            # Цена
            price_item = QtWidgets.QTableWidgetItem(f"{current_price:,.2f}" if current_price else "-")
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
        """Выбор инструмента в избранном."""
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

                for info in self._favorites.values():
                    if info.ticker == ticker:
                        self._current_figi = info.figi
                        current_price = self.app_context.get_quote(info.figi) if self.app_context else 0.0
                        self._current_price = current_price

                        # Устанавливаем в торговую панель
                        self.trading_panel.set_instrument(info, current_price)

                        # Загружаем историю
                        self._load_history(info.figi)
                        break

    def _on_quotes_updated(self, quotes: dict):
        """Обновление котировок."""
        # Обновляем таблицу избранного
        self._update_favorites_table()
        # НЕ обновляем цену в торговой панели автоматически

    def _on_portfolio_updated(self, positions: list):
        """Обновление портфеля из контекста."""
        print(f"[TradingTab] Portfolio updated: {len(positions)} positions")
        self._portfolio_positions = positions
        self._update_favorites_table()

    def _on_buy_clicked(self, instrument: InstrumentInfo, lots: int, price: float):
        """Выставить заявку на покупку."""
        if not self.app_context:
            self.trading_panel.set_result(False, "Нет контекста приложения")
            return

        token = self.app_context.get_current_token()
        account_id = self.app_context.account_id

        if not token or not account_id:
            self.trading_panel.set_result(False, "Нет токена или account_id")
            return

        result = post_order(
            token=token,
            account_id=account_id,
            figi=instrument.figi,
            quantity=lots,
            price=price,
            direction="buy",
        )

        if result.success:
            self.trading_panel.set_result(True, f"Заявка {result.order_id} выставлена")
        else:
            self.trading_panel.set_result(False, result.error or result.message)

    def _on_sell_clicked(self, instrument: InstrumentInfo, lots: int, price: float):
        """Выставить заявку на продажу."""
        if not self.app_context:
            self.trading_panel.set_result(False, "Нет контекста приложения")
            return

        token = self.app_context.get_current_token()
        account_id = self.app_context.account_id

        if not token or not account_id:
            self.trading_panel.set_result(False, "Нет токена или account_id")
            return

        result = post_order(
            token=token,
            account_id=account_id,
            figi=instrument.figi,
            quantity=lots,
            price=price,
            direction="sell",
        )

        if result.success:
            self.trading_panel.set_result(True, f"Заявка {result.order_id} выставлена")
        else:
            self.trading_panel.set_result(False, result.error or result.message)

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
        self._history_thread.finished.connect(self._history_thread.deleteLater)

        self._history_thread.start()

    def _on_history_loaded(self, operations: list):
        """Обработка загруженной истории."""
        self._current_operations = operations

        self.history_table.setRowCount(0)

        for op in operations:
            r = self.history_table.rowCount()
            self.history_table.insertRow(r)

            date_str = op.date.strftime("%Y-%m-%d %H:%M") if hasattr(op.date, "strftime") else str(op.date)
            self.history_table.setItem(r, 0, QtWidgets.QTableWidgetItem(date_str))

            op_type_raw = op.operation_type
            if isinstance(op_type_raw, int):
                op_type = OPERATION_TYPE_MAP.get(op_type_raw, f"type_{op_type_raw}")
            else:
                op_type = str(op_type_raw)

            type_item = QtWidgets.QTableWidgetItem(op_type)
            if "buy" in op_type.lower():
                type_item.setForeground(QtGui.QColor("#4CAF50"))
            elif "sell" in op_type.lower():
                type_item.setForeground(QtGui.QColor("#f44336"))
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
        """Обработка ошибки загрузки истории."""
        self.lbl_status.setText(f"❌ Ошибка: {error[:50]}...")
        print(f"[TradingTab] History error: {error}")

    def _refresh_history_for_selected(self):
        """Обновить историю для выбранного инструмента."""
        if self._current_figi:
            self._load_history(self._current_figi)
        else:
            self.lbl_filter.setText("Сначала выберите инструмент в таблице слева")

    def _clear_cache_and_reload(self):
        """Очистить кэш и перезагрузить историю."""
        clear_history_cache()

        if self._current_figi:
            self.lbl_status.setText("🗑 Кэш очищен, загружаем заново...")
            self._load_history(self._current_figi)
        else:
            QtWidgets.QMessageBox.information(self, "Кэш", "Кэш очищен. Выберите инструмент для загрузки истории.")

    def _on_error(self, error: str):
        """Обработка ошибки."""
        print(f"[TradingTab] ERROR: {error}")
        self.lbl_status.setText(f"❌ Ошибка: {error[:100]}...")
