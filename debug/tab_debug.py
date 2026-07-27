# debug/tab_debug.py
"""
Вкладка "Отладка" - просмотр сырых данных от T-Invest API.
Для отладки и понимания структуры данных.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from PyQt6 import QtCore, QtWidgets

from app.app_context import AppContext
from app.config import TOKEN, REAL_TOKEN, FAVORITES_FILE
from core.account_api import get_accounts, get_portfolio
from core.orders_api import get_orders
from core.operations_api import get_operations
from core.favorites_repo import load_favorites
from core.favorites_trading import get_favorites_summary
from t_tech.invest import Client


class DebugDataLoader(QtCore.QObject):
    """Загрузчик данных для отладки."""
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, data_type: str):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.data_type = data_type

    @QtCore.pyqtSlot()
    def run(self):
        try:
            result = {}

            if self.data_type == "accounts":
                accounts = get_accounts(self.token)
                result = {
                    "accounts": [
                        {
                            "account_id": acc.account_id,
                            "account_type": acc.account_type,
                            "status": acc.status,
                            "currency": acc.currency,
                        }
                        for acc in accounts
                    ]
                }

            elif self.data_type == "portfolio":
                portfolio = get_portfolio(self.token, self.account_id)
                result = {
                    "total_amount_portfolio": portfolio.total_amount_portfolio,
                    "total_amount_shares": portfolio.total_amount_shares,
                    "total_amount_bonds": portfolio.total_amount_bonds,
                    "total_amount_etf": portfolio.total_amount_etf,
                    "total_amount_currencies": portfolio.total_amount_currencies,
                    "positions": [
                        {
                            "figi": pos.figi,
                            "ticker": pos.ticker,
                            "name": pos.name,
                            "instrument_type": pos.instrument_type,
                            "quantity": pos.quantity,
                            "balance": pos.balance,
                            "position_avg_price": pos.position_avg_price,
                            "current_price": pos.current_price,
                        }
                        for pos in portfolio.positions
                    ]
                }

            elif self.data_type == "orders":
                orders = get_orders(self.token, self.account_id)
                result = {
                    "count": len(orders),
                    "orders": [
                        {
                            "order_id": o.order_id,
                            "figi": o.figi,
                            "ticker": o.ticker,
                            "order_type": o.order_type,
                            "status": o.status,
                            "lots_requested": o.lots_requested,
                            "lots_executed": o.lots_executed,
                            "price": o.price,
                            "executed_order_price": o.executed_order_price,
                            "created": o.created.isoformat() if o.created else None,
                            "updated": o.updated.isoformat() if o.updated else None,
                        }
                        for o in orders
                    ]
                }

            elif self.data_type == "fills":
                now = datetime.now(timezone.utc)
                from_date = now - timedelta(days=30)
                operations = get_operations(self.token, self.account_id, from_date, now)
                result = {
                    "count": len(operations),
                    "period_days": 30,
                    "operations": [
                        {
                            "id": op.id,
                            "figi": op.figi,
                            "ticker": op.ticker,
                            "name": op.name,
                            "operation_type": op.operation_type,
                            "quantity": op.quantity,
                            "price": op.price,
                            "amount": op.amount,
                            "currency": op.currency,
                            "date": op.date.isoformat() if op.date else None,
                        }
                        for op in operations
                    ]
                }

            elif self.data_type == "quotes":
                # Загружаем котировки для избранных инструментов (биржевые)
                favorites = load_favorites(FAVORITES_FILE)
                figis = [info.figi for info in favorites.values() if info.figi]

                quotes_result = []
                if figis:
                    with Client(self.token) as client:
                        resp = client.market_data.get_last_prices(figi=figis)
                        for lp in getattr(resp, "last_prices", []) or []:
                            figi = getattr(lp, "figi", "")
                            price = getattr(lp, "price", None)
                            price_value = None
                            if price:
                                price_value = float(getattr(price, "units", 0) or 0) + float(
                                    getattr(price, "nano", 0) or 0) / 1e9

                            ticker = None
                            for info in favorites.values():
                                if info.figi == figi:
                                    ticker = info.ticker
                                    break

                            quotes_result.append({
                                "figi": figi,
                                "ticker": ticker,
                                "price": price_value,
                                "time": getattr(lp, "time", None).isoformat() if getattr(lp, "time", None) else None,
                                "source": "exchange",
                            })

                result = {
                    "count": len(quotes_result),
                    "quotes": quotes_result
                }

            elif self.data_type == "orderbook":
                # Стакан - получаем ближайшие цены покупки (bid) и продажи (ask)
                # Работает даже когда биржа закрыта (внебиржевые торги)
                favorites = load_favorites(FAVORITES_FILE)
                figis = [info.figi for info in favorites.values() if info.figi]

                quotes_result = []
                if figis:
                    with Client(self.token) as client:
                        for figi in figis:
                            try:
                                # Получаем стакан глубиной 10
                                orderbook = client.market_data.get_order_book(instrument_id=figi, depth=10)

                                # Находим ticker из избранного
                                ticker = None
                                for info in favorites.values():
                                    if info.figi == figi:
                                        ticker = info.ticker
                                        break

                                # Цена последней сделки
                                last_price = getattr(orderbook, "last_price", None)
                                last_price_value = None
                                if last_price:
                                    last_price_value = float(getattr(last_price, "units", 0) or 0) + \
                                                       float(getattr(last_price, "nano", 0) or 0) / 1e9

                                # Лучшие цены в стакане
                                best_bid = None
                                best_ask = None

                                bids = getattr(orderbook, "bids", []) or []
                                if bids:
                                    best_bid = bids[0]

                                asks = getattr(orderbook, "asks", []) or []
                                if asks:
                                    best_ask = asks[0]

                                bid_price = None
                                if best_bid:
                                    price = getattr(best_bid, "price", None)
                                    if price:
                                        bid_price = float(getattr(price, "units", 0) or 0) + \
                                                    float(getattr(price, "nano", 0) or 0) / 1e9

                                ask_price = None
                                if best_ask:
                                    price = getattr(best_ask, "price", None)
                                    if price:
                                        ask_price = float(getattr(price, "units", 0) or 0) + \
                                                    float(getattr(price, "nano", 0) or 0) / 1e9

                                quotes_result.append({
                                    "figi": figi,
                                    "ticker": ticker,
                                    "last_price": last_price_value,
                                    "bid_price": bid_price,
                                    "ask_price": ask_price,
                                    "spread": (ask_price - bid_price) if (bid_price and ask_price) else None,
                                    "time": getattr(orderbook, "time", None).isoformat() if getattr(orderbook, "time",
                                                                                                    None) else None,
                                    "source": "orderbook",
                                })
                            except Exception as e:
                                import traceback
                                quotes_result.append({
                                    "figi": figi,
                                    "ticker": None,
                                    "last_price": None,
                                    "bid_price": None,
                                    "ask_price": None,
                                    "spread": None,
                                    "time": None,
                                    "source": f"error: {traceback.format_exc()[:100]}",
                                })

                result = {
                    "count": len(quotes_result),
                    "quotes": quotes_result
                }

            elif self.data_type == "trading":
                summary = get_favorites_summary(self.token, self.account_id)
                result = summary

            self.loaded.emit({
                "data_type": self.data_type,
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()


class DebugTab(QtWidgets.QWidget):
    """Вкладка отладки."""

    def __init__(self, app_context: AppContext = None, parent=None):
        super().__init__(parent)

        self.app_context = app_context
        self._load_thread: Optional[QtCore.QThread] = None
        self._load_worker: Optional[DebugDataLoader] = None

        if self.app_context:
            self.app_context.account_changed.connect(self._on_account_changed)

        # Выбор типа данных
        self.data_type_combo = QtWidgets.QComboBox()
        self.data_type_combo.addItems([
            "accounts - Счета",
            "portfolio - Портфель",
            "orders - Заявки",
            "fills - Исполнения (30 дней)",
            "quotes - Котировки (биржевые)",
            "orderbook - Стакан (bid/ask)",
            "trading - Торговля (избранное)",
        ])
        self.data_type_combo.setCurrentIndex(4)

        # Кнопка загрузки
        self.btn_load = QtWidgets.QPushButton("📥 Загрузить")
        self.btn_load.setMinimumHeight(30)
        self.btn_load.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.btn_load.clicked.connect(self._on_load_clicked)

        # Поле account_id
        self.ed_account_id = QtWidgets.QLineEdit()
        self.ed_account_id.setPlaceholderText("account_id")
        self.ed_account_id.setMaximumWidth(300)

        # Верхняя панель
        top_layout = QtWidgets.QHBoxLayout()
        top_layout.addWidget(QtWidgets.QLabel("Данные:"))
        top_layout.addWidget(self.data_type_combo, 1)
        top_layout.addWidget(QtWidgets.QLabel("Account:"))
        top_layout.addWidget(self.ed_account_id)
        top_layout.addWidget(self.btn_load)
        top_layout.addStretch()

        # Статус
        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setStyleSheet("color: #666; font-size: 10px;")

        # JSON вывод
        self.json_output = QtWidgets.QTextEdit()
        self.json_output.setReadOnly(True)
        self.json_output.setFontFamily("Consolas")
        self.json_output.setFontPointSize(10)
        self.json_output.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 8px;
            }
        """)

        # Кнопка копирования
        self.btn_copy = QtWidgets.QPushButton("📋 Копировать JSON")
        self.btn_copy.setMaximumWidth(150)
        self.btn_copy.clicked.connect(self._copy_json)

        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.addWidget(self.lbl_status, 1)
        bottom_layout.addWidget(self.btn_copy)

        # Компоновка
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_layout)
        layout.addWidget(self.lbl_status)
        layout.addWidget(self.json_output, 1)
        layout.addLayout(bottom_layout)

        # Автозаполнение account_id
        if self.app_context:
            self.ed_account_id.setText(self.app_context.account_id)

    def _on_account_changed(self, account_id: str):
        self.ed_account_id.setText(account_id)

    def _on_load_clicked(self):
        data_type = str(self.data_type_combo.currentText()).split(" - ")[0].strip()
        account_id = self.ed_account_id.text().strip()

        if not account_id and data_type != "quotes":
            self.lbl_status.setText("❌ Укажите account_id")
            return

        self.btn_load.setEnabled(False)
        self.btn_load.setText("⏳ Загрузка...")
        self.lbl_status.setText(f"⏳ Загрузка {data_type}...")
        self.json_output.setText("")

        self._load_thread = QtCore.QThread(self)
        self._load_worker = DebugDataLoader(TOKEN, account_id, data_type)
        self._load_worker.moveToThread(self._load_thread)

        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.loaded.connect(self._on_loaded)
        self._load_worker.error.connect(self._on_error)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.start()

    def _on_loaded(self, payload: dict):
        self.btn_load.setEnabled(True)
        self.btn_load.setText("📥 Загрузить")

        data_type = payload.get("data_type", "")
        result = payload.get("result", {})
        timestamp = payload.get("timestamp", "")

        # Форматируем JSON
        json_str = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        self.json_output.setText(json_str)

        count = result.get("count", 0) if isinstance(result, dict) else 0
        self.lbl_status.setText(f"✅ {data_type}: {count} записей | {timestamp}")

    def _on_error(self, error: str):
        self.btn_load.setEnabled(True)
        self.btn_load.setText("📥 Загрузить")
        self.lbl_status.setText(f"❌ Ошибка")
        self.json_output.setText(error)

    def _copy_json(self):
        text = self.json_output.toPlainText()
        if text:
            QtWidgets.QApplication.clipboard().setText(text)
            self.lbl_status.setText("📋 JSON скопирован в буфер обмена")
