# tabs/tab_debug.py
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
    loaded = QtCore.pyqtSignal(object)  # dict с данными
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, data_type: str):
        super().__init__()
        self.token = token
        self.account_id = account_id
        self.data_type = data_type  # "orders", "portfolio", "accounts", "fills"

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
                # Загружаем котировки для избранных инструментов
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

                            # Находим ticker из избранного
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
                            })

                result = {
                    "count": len(quotes_result),
                    "quotes": quotes_result
                }

            elif self.data_type == "trading":
                # Получаем информацию о торговле избранными инструментами
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

        # Подключаемся к контексту
        if self.app_context:
            self.app_context.account_changed.connect(self._on_account_changed)

        # Выбор типа данных
        self.data_type_combo = QtWidgets.QComboBox()
        self.data_type_combo.addItems([
            "accounts - Список счетов",
            "portfolio - Портфель",
            "orders - Активные заявки",
            "fills - История сделок (операции)",
            "quotes - Котировки избранного",
            "trading - Состояние торговли избранного",
        ])
        self.data_type_combo.setCurrentIndex(0)

        # Кнопки
        self.btn_load = QtWidgets.QPushButton("📥 Загрузить данные")
        self.btn_load.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.btn_load.clicked.connect(self._load_data)

        self.btn_clear = QtWidgets.QPushButton("🗑 Очистить")
        self.btn_clear.clicked.connect(self._clear_all)

        # Верхняя панель
        top_layout = QtWidgets.QHBoxLayout()
        top_layout.addWidget(QtWidgets.QLabel("🔍 Отладка реального счёта:"))
        top_layout.addWidget(self.data_type_combo)
        top_layout.addWidget(self.btn_load)
        top_layout.addWidget(self.btn_clear)
        top_layout.addStretch()

        # Статус
        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setStyleSheet("color: #666; font-size: 10px;")
        self._update_status()

        # Текстовые поля для данных
        self.text_raw = QtWidgets.QTextEdit()
        self.text_raw.setPlaceholderText("Сырые данные (JSON)...")
        self.text_raw.setReadOnly(True)
        self.text_raw.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, Monaco, monospace;
                font-size: 11px;
                background: #f8f9fa;
                border: 1px solid #ddd;
                border-radius: 3px;
            }
        """)

        self.text_formatted = QtWidgets.QTextEdit()
        self.text_formatted.setPlaceholderText("Отформатированные данные...")
        self.text_formatted.setReadOnly(True)
        self.text_formatted.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, Monaco, monospace;
                font-size: 11px;
                background: #fff;
                border: 1px solid #ddd;
                border-radius: 3px;
            }
        """)

        # Вкладки для разных форматов
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.text_raw, "📄 JSON (сырой)")
        self.tabs.addTab(self.text_formatted, "📋 Отформатировано")

        # Основная компоновка
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_layout)
        layout.addWidget(self.lbl_status)
        layout.addWidget(self.tabs)

        # Подсказка
        hint = QtWidgets.QLabel(
            "💡 Выделите текст в любом поле и нажмите Ctrl+C для копирования. "
            "Данные можно сохранить в файл через правый клик → Сохранить как..."
        )
        hint.setStyleSheet("color: #666; font-size: 10px; font-style: italic;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def set_account_id(self, account_id: str):
        """Установить account_id (для совместимости)."""
        if self.app_context:
            self.app_context.account_id = account_id

    def _on_account_changed(self, account_id: str):
        """Обновление account_id."""
        print(f"[DebugTab] account_changed: {account_id}")
        self._update_status()

    def _update_status(self):
        """Обновить статус с account_id."""
        if self.app_context:
            account_id = self.app_context.real_account_id
            if account_id:
                self.lbl_status.setText(f"✅ Реальный счёт: {account_id[:8]}...")
            else:
                self.lbl_status.setText("❌ Нет account_id реального счёта")
        else:
            self.lbl_status.setText("❌ Нет контекста")

    def _get_token(self) -> str:
        """Получить токен реального счёта."""
        return REAL_TOKEN

    def _load_data(self):
        """Загрузить данные."""
        self._update_status()

        # Всегда используем реальный счёт
        if self.app_context:
            self.app_context.switch_to_real()

        token = self._get_token()

        # Проверяем токен
        if not token or token == "paste_your_t_invest_token_here":
            self.lbl_status.setText("❌ Токен реального счёта не настроен")
            print(f"[DebugTab] Real token not configured")
            return

        # Получаем account_id из контекста
        account_id = self.app_context.real_account_id if self.app_context else ""

        # Для accounts account_id не нужен
        if not account_id and self.data_type_combo.currentText() != "accounts - Список счетов":
            self.lbl_status.setText(f"❌ Нет account_id реального счёта")
            print(f"[DebugTab] load_data: account_id={account_id}, data_type={self.data_type_combo.currentText()}")
            return

        print(f"[DebugTab] Loading: account_type=real, account_id={account_id[:8] if account_id else 'N/A'}...")

        # Определяем тип данных
        data_type_map = {
            "accounts - Список счетов": "accounts",
            "portfolio - Портфель": "portfolio",
            "orders - Активные заявки": "orders",
            "fills - История сделок (операции)": "fills",
            "quotes - Котировки избранного": "quotes",
            "trading - Состояние торговли избранного": "trading",
        }
        data_type = data_type_map.get(self.data_type_combo.currentText(), "accounts")

        # Передаём account_id в загрузчик
        self._load_thread = QtCore.QThread(self)
        self._load_worker = DebugDataLoader(token, account_id, data_type)

        # Запускаем загрузку
        self.btn_load.setEnabled(False)
        self.lbl_status.setText(f"⏳ Загрузка {data_type}...")

        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.loaded.connect(self._on_data_loaded)
        self._load_worker.error.connect(self._on_error)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.finished.connect(self._on_finished)

        self._load_thread.start()

    def _on_data_loaded(self, data: dict):
        """Обработка загруженных данных."""
        result = data.get("result", {})
        timestamp = data.get("timestamp", "")
        data_type = data.get("data_type", "")

        # Сырой JSON
        raw_json = json.dumps(result, indent=2, ensure_ascii=False)
        self.text_raw.setPlainText(raw_json)

        # Отформатированный вид
        formatted = self._format_data(result, data_type)
        self.text_formatted.setPlainText(formatted)

        count = len(result.get("orders", [])) or len(result.get("positions", [])) or len(result.get("accounts", []))
        self.lbl_status.setText(f"✅ Загружено: {count} записей ({data_type}) в {timestamp}")

    def _format_data(self, result: dict, data_type: str) -> str:
        """Отформатировать данные для удобного чтения."""
        lines = []
        lines.append(f"Тип данных: {data_type}")
        lines.append(f"Время загрузки: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 60)
        lines.append("")

        if data_type == "accounts":
            accounts = result.get("accounts", [])
            lines.append(f"Всего счетов: {len(accounts)}")
            lines.append("")
            for i, acc in enumerate(accounts, 1):
                lines.append(f"[{i}] {acc.get('account_id', 'N/A')}")
                lines.append(f"    Тип: {acc.get('account_type', 'N/A')}")
                lines.append(f"    Статус: {acc.get('status', 'N/A')}")
                lines.append(f"    Валюта: {acc.get('currency', 'N/A')}")
                lines.append("")

        elif data_type == "portfolio":
            lines.append(f"Общая стоимость: {result.get('total_amount_portfolio', 0):,.2f} ₽")
            lines.append(f"Акции: {result.get('total_amount_shares', 0):,.2f} ₽")
            lines.append(f"Облигации: {result.get('total_amount_bonds', 0):,.2f} ₽")
            lines.append(f"ETF: {result.get('total_amount_etf', 0):,.2f} ₽")
            lines.append(f"Валюта: {result.get('total_amount_currencies', 0):,.2f} ₽")
            lines.append("")
            lines.append(f"Позиций: {len(result.get('positions', []))}")
            lines.append("")
            for pos in result.get("positions", [])[:20]:  # Первые 20
                lines.append(f"  • {pos.get('ticker', 'N/A')} | {pos.get('name', 'N/A')}")
                lines.append(f"    FIGI: {pos.get('figi', 'N/A')}")
                lines.append(f"    Кол-во: {pos.get('quantity', 0):,.6f}")
                lines.append(f"    Средняя цена: {pos.get('position_avg_price', 0):,.2f}")
                current_price = pos.get('current_price')
                lines.append(f"    Тек. цена: {current_price:,.2f}" if current_price else "    Тек. цена: N/A")
                lines.append("")
            if len(result.get("positions", [])) > 20:
                lines.append(f"... и ещё {len(result.get('positions', [])) - 20} позиций")

        elif data_type == "orders":
            lines.append(f"Всего заявок: {result.get('count', 0)}")
            lines.append("")
            for order in result.get("orders", []):
                lines.append(f"  • {order.get('order_id', 'N/A')[:8]}...")
                lines.append(f"    Ticker: {order.get('ticker', 'N/A')}")
                lines.append(f"    Тип: {order.get('order_type', 'N/A')}")
                lines.append(f"    Статус: {order.get('status', 'N/A')}")
                lines.append(f"    Кол-во: {order.get('lots_requested', 0)} / {order.get('lots_executed', 0)}")
                lines.append(f"    Цена: {order.get('price', 0):,.2f}")
                lines.append(f"    Создана: {order.get('created', 'N/A')}")
                lines.append("")

        elif data_type == "fills":
            lines.append(f"Всего операций: {result.get('count', 0)}")
            lines.append(f"Период: {result.get('period_days', 30)} дней")
            lines.append("")
            for op in result.get("operations", [])[:30]:  # Первые 30
                lines.append(f"  • {op.get('date', 'N/A')[:10]}")
                lines.append(f"    Ticker: {op.get('ticker', 'N/A')}")
                lines.append(f"    Тип: {op.get('operation_type', 'N/A')}")
                quantity = op.get('quantity', 0)
                lines.append(f"    Кол-во: {quantity:,.6f}" if quantity else "    Кол-во: 0")
                price = op.get('price')
                lines.append(f"    Цена: {price:,.2f}" if price else "    Цена: N/A")
                amount = op.get('amount')
                lines.append(
                    f"    Сумма: {amount:,.2f} {op.get('currency', 'RUB')}" if amount else f"    Сумма: N/A {op.get('currency', 'RUB')}")
                lines.append("")
            if len(result.get("operations", [])) > 30:
                lines.append(f"... и ещё {len(result.get('operations', [])) - 30} операций")

        elif data_type == "quotes":
            lines.append(f"Всего котировок: {result.get('count', 0)}")
            lines.append("")
            for quote in result.get("quotes", []):
                lines.append(f"  • {quote.get('ticker', 'N/A')} ({quote.get('figi', 'N/A')[:8]}...)")
                price = quote.get('price')
                lines.append(f"    Цена: {price:,.2f} ₽" if price else "    Цена: N/A")
                time_str = quote.get('time', 'N/A')
                if time_str and time_str != 'N/A':
                    lines.append(f"    Время: {time_str[:19]}")
                lines.append("")

        elif data_type == "trading":
            lines.append("📊 СВОДКА ПО ИЗБРАННОМУ")
            lines.append("=" * 50)
            lines.append(f"Всего инструментов: {result.get('total_instruments', 0)}")
            lines.append(f"Рыночная стоимость: {result.get('total_market_value', 0):,.2f} ₽")
            lines.append(f"Средняя стоимость: {result.get('total_cost', 0):,.2f} ₽")
            lines.append(
                f"P&L: {result.get('total_unrealized_pnl', 0):,.2f} ₽ ({result.get('total_unrealized_pnl_percent', 0):.2f}%)")
            lines.append("")
            lines.append(f"В плюсе: {result.get('profitable_count', 0)}")
            lines.append(f"В минусе: {result.get('unprofitable_count', 0)}")
            lines.append(f"Без изменений: {result.get('flat_count', 0)}")
            lines.append("")
            lines.append("=" * 50)
            lines.append("ДЕТАЛИ ПО ИНСТРУМЕНТАМ:")
            lines.append("=" * 50)

            for inst in result.get("instruments", []):
                pnl = inst.get('unrealized_pnl', 0)
                pnl_color = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
                trading_status = inst.get('trading_status', 'unknown')

                # Статус торгов
                status_emoji = "🟢" if trading_status == "MARKET_STATUS_OPEN" else "🔴" if trading_status == "MARKET_STATUS_CLOSED" else "🟡"

                lines.append(
                    f"{pnl_color} {inst.get('ticker', 'N/A')} | {inst.get('name', 'N/A')} {status_emoji} {trading_status}")
                lines.append(f"    FIGI: {inst.get('figi', 'N/A')}")
                lines.append(f"    Кол-во: {inst.get('quantity', 0):,.6f}")
                lines.append(f"    Средняя: {inst.get('average_price', 0):,.2f} ₽")
                lines.append(f"    Текущая: {inst.get('current_price', 0):,.2f} ₽")
                lines.append(f"    Рыночная: {inst.get('market_value', 0):,.2f} ₽")
                lines.append(f"    P&L: {pnl:,.2f} ₽ ({inst.get('unrealized_pnl_percent', 0):.2f}%)")
                lines.append("")

        return "\n".join(lines)

    def _on_error(self, error: str):
        """Обработка ошибки."""
        self.text_raw.setPlainText(f"❌ Ошибка:\n\n{error}")
        self.text_formatted.setPlainText("")
        self.lbl_status.setText("❌ Ошибка загрузки")

    def _on_finished(self):
        """Завершение загрузки."""
        self.btn_load.setEnabled(True)
        self._load_thread = None
        self._load_worker = None

    def _clear_all(self):
        """Очистить все поля."""
        self.text_raw.clear()
        self.text_formatted.clear()
        self.lbl_status.setText("🗑 Очищено")
