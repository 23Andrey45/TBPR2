# tabs/tab_sandbox_trading.py — ИСПРАВЛЕННАЯ ВЕРСИЯ
# Все логи выводятся в консоль через print()

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import uuid
import traceback
import sys
from typing import Optional, Any

from PyQt6 import QtCore, QtWidgets

# ✅ ЛОГИРОВАНИЕ для отладки - ВЫВОД В КОНСОЛЬ
_DEBUG_LOG = []


def _log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    log_line = f"[SANDBOX-TAB {ts}] {msg}"
    _DEBUG_LOG.append(log_line)
    if len(_DEBUG_LOG) > 200:
        _DEBUG_LOG.pop(0)
    print(log_line)
    sys.stdout.flush()


# ✅ ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ИСКЛЮЧЕНИЙ
def _global_exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    print("\n" + "=" * 60)
    print("!!! КРИТИЧЕСКАЯ ОШИБКА (Global Exception Handler) !!!")
    print("=" * 60)
    print(f"Тип: {exc_type.__name__}")
    print(f"Сообщение: {exc_value}")
    print("\nTraceback:")
    traceback.print_exception(exc_type, exc_value, exc_traceback)
    print("=" * 60)
    sys.stdout.flush()


sys.excepthook = _global_exception_handler

from app.config import TOKEN, DATA_DIR, DB_FILE
from core.instruments_catalog import InstrumentInfo

# ✅ Импортируем ОБЩИЕ воркеры
from workers import (
    SandboxAccountsLoader,
    SandboxMoneyBalanceLoader,
    SandboxPostLimitOrderLoader,
    SandboxActiveOrdersLoader,
    CancelSandboxOrderWorker,
    RecentDealsLoader,
    OrderStatesLoader,
)

# Импортируем базу данных - объявляем переменные ДО импорта
DB_ENABLED = False
init_db = None
Order = None
Fill = None
OrderRepository = None
FillRepository = None

try:
    import db

    init_db = db.init_db
    Order = db.Order
    Fill = db.Fill
    OrderRepository = db.OrderRepository
    FillRepository = db.FillRepository

    DB_ENABLED = True
    print("[SANDBOX-TAB] Database module loaded successfully")
except Exception as e:
    print(f"[SANDBOX-TAB] WARNING: Database module not loaded: {e}")
    import traceback

    traceback.print_exc()

import sys

sys.stdout.flush()
from tabs.instruments_controller import InstrumentsController
from tabs.quotes_hub import QuotesHub
from tabs.trading_context import TradingContext
from tabs.instrument_picker_widget import kind_to_short
from tabs.sandbox_favorites_picker import FavoritesOnlyPicker

from core.sandbox_orders_api import PlaceOrderAttempt, ActiveOrder


class SandboxTradingTab(QtWidgets.QWidget):
    ORDERS_CACHE_FILE = DATA_DIR / "orders_cache.json"
    FILLS_CACHE_FILE = DATA_DIR / "fills_cache.json"
    DEBUG_ORDERS_LOG = False
    MAX_ACTIVE_ROWS_RENDER = 500
    MAX_HISTORY_ROWS_RENDER = 500
    MIN_STATUS_REFRESH_INTERVAL_MS = 2000

    def __init__(
            self,
            instruments_controller: InstrumentsController,
            quotes_hub: QuotesHub,
            trading_context: TradingContext,
            parent=None,
    ):
        super().__init__(parent)

        self.instr_controller = instruments_controller
        self.quotes_hub = quotes_hub
        self.trading_context = trading_context
        self.picker = FavoritesOnlyPicker(
            controller=self.instr_controller,
            quotes_hub=self.quotes_hub,
            trading_context=self.trading_context,
            parent=self,
        )

        self._selected_instrument: Optional[InstrumentInfo] = None
        self._account_id: str = ""
        self._by_figi: dict[str, InstrumentInfo] = {}

        self.btn_refresh_accounts = QtWidgets.QPushButton("Обновить sandbox аккаунты")
        self.cb_accounts = QtWidgets.QComboBox()
        self.cb_accounts.setMinimumWidth(260)
        self.lbl_balance = QtWidgets.QLabel("Доступно RUB: -")

        # ✅ Инструмент + чекбокс справа
        selected_line = QtWidgets.QHBoxLayout()
        self.lbl_selected = QtWidgets.QLabel("Инструмент: не выбран")
        self.lbl_selected.setWordWrap(True)
        self.cb_only_selected = QtWidgets.QCheckBox("только выбранное")
        selected_line.addWidget(self.lbl_selected, 1)
        selected_line.addWidget(self.cb_only_selected)

        self.ed_lots = QtWidgets.QLineEdit("1")
        self.ed_lots.setMaximumWidth(70)
        self.ed_price = QtWidgets.QLineEdit("250.00")
        self.ed_price.setMaximumWidth(110)
        self.btn_buy_limit = QtWidgets.QPushButton("BUY LIMIT")
        self.btn_sell_limit = QtWidgets.QPushButton("SELL LIMIT")
        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)

        # ✅ Таблица 1: Созданные заявки
        created_header_line = QtWidgets.QHBoxLayout()
        self.lbl_created_orders = QtWidgets.QLabel("<b>Созданные заявки</b>")
        self.btn_refresh_status = QtWidgets.QPushButton("🔄 Обновить статус")
        created_header_line.addWidget(self.lbl_created_orders)
        created_header_line.addWidget(self.btn_refresh_status)
        created_header_line.addStretch()

        self.tbl_active = QtWidgets.QTableWidget(0, 9)
        self.tbl_active.setHorizontalHeaderLabels(
            ["order_id", "Ticker", "Side", "Type", "Lots req", "Lots exec", "Price", "Status", "Удалить"])
        self.tbl_active.horizontalHeader().setStretchLastSection(True)
        self.tbl_active.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        # ✅ Таблица 2: Активные заявки (сервер)
        self.lbl_server_orders = QtWidgets.QLabel("<b>Активные заявки</b>")
        self.lbl_server_orders_count = QtWidgets.QLabel("Активные ордера на сервере: 0")
        self.btn_refresh_server_orders = QtWidgets.QPushButton("🔄 Обновить")
        self.btn_refresh_server_orders.setMaximumWidth(150)

        server_header_line = QtWidgets.QHBoxLayout()
        server_header_line.addWidget(self.lbl_server_orders)
        server_header_line.addWidget(self.btn_refresh_server_orders)
        server_header_line.addWidget(self.lbl_server_orders_count)
        server_header_line.addStretch()

        self.tbl_server_orders = QtWidgets.QTableWidget(0, 9)
        self.tbl_server_orders.setHorizontalHeaderLabels(
            ["order_id", "Ticker", "Side", "Type", "Lots req", "Lots exec", "Price", "Status", "Удалить"])
        self.tbl_server_orders.horizontalHeader().setStretchLastSection(True)
        self.tbl_server_orders.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_server_orders.cellClicked.connect(self._on_server_order_cell_clicked)

        # ✅ Таблица 3: История
        self.lbl_history = QtWidgets.QLabel("<b>История</b>")
        self.tbl_history = QtWidgets.QTableWidget(0, 9)
        self.tbl_history.setHorizontalHeaderLabels(
            ["time", "Ticker", "Side", "Type", "Lots", "Price", "Status", "order_id", "Источник"])
        self.tbl_history.horizontalHeader().setStretchLastSection(True)
        self.tbl_history.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)

        acc_line = QtWidgets.QHBoxLayout()
        acc_line.addWidget(self.btn_refresh_accounts)
        acc_line.addWidget(self.lbl_status)
        acc_line.addStretch()
        acc_line.addWidget(QtWidgets.QLabel("Account:"))
        acc_line.addWidget(self.cb_accounts, 1)
        acc_line.addWidget(self.lbl_balance)

        right_layout.addLayout(acc_line)
        right_layout.addLayout(selected_line)

        params = QtWidgets.QHBoxLayout()
        params.addWidget(QtWidgets.QLabel("Lots:"))
        params.addWidget(self.ed_lots)
        params.addWidget(QtWidgets.QLabel("Price:"))
        params.addWidget(self.ed_price)
        params.addStretch()
        right_layout.addLayout(params)

        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(self.btn_buy_limit)
        btns.addWidget(self.btn_sell_limit)
        btns.addStretch()
        right_layout.addLayout(btns)

        # ✅ Splitter с тремя таблицами + заголовки
        split_right = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)

        # Таблица 1
        tbl1_widget = QtWidgets.QWidget()
        tbl1_layout = QtWidgets.QVBoxLayout(tbl1_widget)
        tbl1_layout.setContentsMargins(0, 0, 0, 0)
        tbl1_layout.addLayout(created_header_line)
        tbl1_layout.addWidget(self.tbl_active)
        split_right.addWidget(tbl1_widget)

        # Таблица 2
        tbl2_widget = QtWidgets.QWidget()
        tbl2_layout = QtWidgets.QVBoxLayout(tbl2_widget)
        tbl2_layout.setContentsMargins(0, 0, 0, 0)
        tbl2_layout.addLayout(server_header_line)
        tbl2_layout.addWidget(self.tbl_server_orders)
        split_right.addWidget(tbl2_widget)

        # Таблица 3
        tbl3_widget = QtWidgets.QWidget()
        tbl3_layout = QtWidgets.QVBoxLayout(tbl3_widget)
        tbl3_layout.setContentsMargins(0, 0, 0, 0)
        tbl3_layout.addWidget(self.lbl_history)
        tbl3_layout.addWidget(self.tbl_history)
        split_right.addWidget(tbl3_widget)

        split_right.setStretchFactor(0, 2)
        split_right.setStretchFactor(1, 1)
        split_right.setStretchFactor(2, 2)
        right_layout.addWidget(split_right)

        main_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        main_split.addWidget(self.picker)
        main_split.addWidget(right_panel)
        main_split.setStretchFactor(0, 5)
        main_split.setStretchFactor(1, 5)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(main_split)

        # Состояния
        self._jobs: list[tuple[QtCore.QThread, QtCore.QObject]] = []
        self._active_loading = False
        self._balance_loading = False
        self._deals_loading = False
        self._deals_enabled = True
        self._order_state_enabled = True
        self._order_state_loading = False
        self._orders_poll_blocked_until: Optional[datetime] = None
        self._is_rendering_tables = False
        self._server_active_by_id: dict[str, ActiveOrder] = {}
        self._orders_cache: list[dict[str, Any]] = self._load_orders_cache()
        self._fills_cache: list[dict[str, Any]] = self._load_fills_cache()
        self._fills_cache = self._keep_last_3_days(self._fills_cache)
        self._render_scheduled = False
        self._last_status_refresh_time: Optional[datetime] = None
        self._last_render_time: Optional[datetime] = None
        self._status_lock = QtCore.QMutex()
        self._status_cycle_running = False
        self._status_cycle_pending = False
        self._updating = False
        self._refresh_count = 0
        self._max_refreshes_per_minute = 30
        self._refresh_times: list[datetime] = []

        # Связи
        self.picker.instrument_selected.connect(self._on_instrument_selected)
        self.btn_refresh_accounts.clicked.connect(self.refresh_accounts)
        self.cb_accounts.currentIndexChanged.connect(self._on_account_changed)
        self.btn_buy_limit.clicked.connect(lambda: self._place_limit("BUY"))
        self.btn_sell_limit.clicked.connect(lambda: self._place_limit("SELL"))
        self.cb_only_selected.toggled.connect(lambda *_: self._request_render())
        self.btn_refresh_status.clicked.connect(self.request_status_refresh)
        self.tbl_active.cellClicked.connect(self._on_active_cell_clicked)
        self.btn_refresh_server_orders.clicked.connect(self._refresh_server_orders_manual)

        _log("UI connections established")
        self.instr_controller.shares_updated.connect(self._reindex_figi)
        self.instr_controller.bonds_updated.connect(self._reindex_figi)
        self.instr_controller.etfs_updated.connect(self._reindex_figi)

        # Таймеры
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(15000)
        self._poll_timer.timeout.connect(self.request_status_refresh)

        self._qty_timer = QtCore.QTimer(self)
        self._qty_timer.setInterval(10000)
        self._qty_timer.timeout.connect(self._refresh_quantities_only)

        # Инициализация базы данных
        if DB_ENABLED and init_db is not None:
            try:
                init_db(DB_FILE)
                _log("Database initialized")
            except Exception as e:
                _log(f"Database init ERROR: {e}")
                # Не меняем глобальный DB_ENABLED

        _log("=" * 50)
        _log("SandboxTradingTab INITIALIZED")
        _log(f"Database enabled: {DB_ENABLED}")
        _log("=" * 50)

        self._request_render()
        QtCore.QTimer.singleShot(0, self.refresh_accounts)

    def stop(self):
        self._poll_timer.stop()
        self._qty_timer.stop()

        # Закрываем базу данных
        if DB_ENABLED:
            try:
                from db import close_db
                close_db()
                _log("Database closed")
            except Exception as e:
                _log(f"DB close ERROR: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        _log("showEvent: tab became visible")
        if not self._poll_timer.isActive():
            self._poll_timer.start()
        if not self._qty_timer.isActive():
            self._qty_timer.start()
        QtCore.QTimer.singleShot(100, self.request_status_refresh)

    def hideEvent(self, event):
        _log("hideEvent: tab became hidden")
        self._poll_timer.stop()
        self._qty_timer.stop()
        if self._status_lock.tryLock(0):
            try:
                self._status_cycle_pending = False
            finally:
                self._status_lock.unlock()
        super().hideEvent(event)

    def _reindex_figi(self, *_):
        self._by_figi = {}
        for info in self.instr_controller.favorites():
            if info.figi:
                self._by_figi[info.figi] = info

    def _refresh_quantities_only(self):
        if not self.isVisible() or self._updating:
            return
        self.picker.refresh_quantities()

    def _check_refresh_rate_limit(self) -> bool:
        now = datetime.now()
        self._refresh_times = [t for t in self._refresh_times if (now - t).total_seconds() < 60]
        if len(self._refresh_times) >= self._max_refreshes_per_minute:
            _log(f"RATE LIMIT: {len(self._refresh_times)} refreshes in last minute")
            return False
        self._refresh_times.append(now)
        self._refresh_count += 1
        return True

    def _run_worker(self, worker: QtCore.QObject, on_loaded=None):
        active_jobs = [(t, w) for (t, w) in self._jobs if t.isRunning()]
        if len(active_jobs) >= 5:
            _log(f"SKIP worker: too many active jobs ({len(active_jobs)})")
            worker.deleteLater()
            return
        self._jobs = [(t, w) for (t, w) in self._jobs if t.isRunning()]

        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        if hasattr(worker, "loaded") and on_loaded is not None:
            worker.loaded.connect(on_loaded, QtCore.Qt.ConnectionType.QueuedConnection)
        if hasattr(worker, "error"):
            worker.error.connect(self._on_worker_error, QtCore.Qt.ConnectionType.QueuedConnection)
        if hasattr(worker, "finished"):
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
        thread.started.connect(worker.run)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._cleanup_job(t))
        # ✅ Исправление: используем timerId для проверки существования
        timeout_timer = QtCore.QTimer(self)
        timeout_timer.setSingleShot(True)
        timeout_timer.timeout.connect(lambda: self._force_cleanup_worker_safe(thread, worker, timeout_timer))
        timeout_timer.start(30000)
        self._jobs.append((thread, worker))
        thread.start()
        _log(f"Started worker: {worker.__class__.__name__}, total jobs: {len(self._jobs)}")

    def _force_cleanup_worker_safe(self, thread: QtCore.QThread, worker: QtCore.QObject, timer: QtCore.QTimer):
        """✅ Безопасная очистка — проверяем существование объектов."""
        timer.deleteLater()
        try:
            if thread.isRunning():
                _log(f"Force cleanup worker: {worker.__class__.__name__}")
                thread.quit()
                thread.wait(1000)
            self._cleanup_job(thread)
        except RuntimeError:
            pass  # Объект уже удалён

    def _force_cleanup_worker(self, thread: QtCore.QThread, worker: QtCore.QObject):
        """✅ Старый метод для совместимости."""
        try:
            if thread.isRunning():
                _log(f"Force cleanup worker: {worker.__class__.__name__}")
                thread.quit()
                thread.wait(1000)
            self._cleanup_job(thread)
        except RuntimeError:
            pass  # Объект уже удалён

    def _cleanup_job(self, thread: QtCore.QThread):
        old_count = len(self._jobs)
        self._jobs = [(t, w) for (t, w) in self._jobs if t is not thread]
        if len(self._jobs) < old_count:
            _log(f"_cleanup_job: removed 1 job, remaining: {len(self._jobs)}")

    def _on_worker_error(self, tb: str):
        self._active_loading = False
        self._balance_loading = False
        self._deals_loading = False
        self._order_state_loading = False
        _log(f"_on_worker_error: {tb[:200]}...")
        if "RESOURCE_EXHAUSTED" in tb and "GetSandboxOrders" in tb:
            wait_sec = self._extract_ratelimit_reset(tb)
            self._orders_poll_blocked_until = datetime.now(timezone.utc) + timedelta(seconds=wait_sec)
            self.lbl_status.setText(f"Лимит API по заявкам исчерпан, ждем {wait_sec} сек")
            _log(f"RATE LIMIT: waiting {wait_sec} sec")
            self._try_finish_status_cycle()
            return
        self.lbl_status.setText("Ошибка (см. консоль)")
        print("\n" + "=" * 60)
        print("!!! ОШИБКА WORKER (SandboxTradingTab) !!!")
        print("=" * 60)
        print(tb)
        print("=" * 60 + "\n")
        sys.stdout.flush()
        self._try_finish_status_cycle()

    def _extract_ratelimit_reset(self, tb: str) -> int:
        m = re.search(r"ratelimit_reset=(\d+)", tb)
        if not m:
            return 3
        try:
            return max(2, int(m.group(1)) + 1)
        except Exception:
            return 3

    def _on_instrument_selected(self, info: InstrumentInfo):
        self._selected_instrument = info
        self.lbl_selected.setText(f"Инструмент: {kind_to_short(info.kind)} | {info.ticker} | {info.name} | {info.isin}")
        price = self.picker.get_price_for(info)
        if price and price != "-":
            self.ed_price.setText(price)
        self._request_render()

    def refresh_accounts(self):
        self.lbl_status.setText("Загрузка sandbox аккаунтов...")
        self._run_worker(SandboxAccountsLoader(TOKEN), self._on_accounts_loaded)

    def _on_accounts_loaded(self, accounts: list[Any]):
        self.cb_accounts.clear()
        for a in accounts:
            acc_id = getattr(a, "account_id", "") or getattr(a, "id", "")
            self.cb_accounts.addItem(str(acc_id), str(acc_id))
        if accounts:
            self._account_id = str(self.cb_accounts.itemData(0))
            self.trading_context.set_account_id(self._account_id)
            self.lbl_status.setText(f"Аккаунтов: {len(accounts)}")
            self.refresh_balance()
            self.request_status_refresh()
        else:
            self._account_id = ""
            self.lbl_balance.setText("Доступно RUB: -")
            self.lbl_status.setText("Аккаунтов: 0 (создай в вкладке Sandbox счёт)")
            self._request_render()

    def _on_account_changed(self):
        self._account_id = str(self.cb_accounts.currentData() or "")
        self.trading_context.set_account_id(self._account_id)
        self.refresh_balance()
        self.request_status_refresh()

    def refresh_balance(self):
        if not self._account_id:
            self.lbl_balance.setText("Доступно RUB: -")
            return
        if self._balance_loading:
            return
        self._balance_loading = True
        self._run_worker(SandboxMoneyBalanceLoader(TOKEN, self._account_id), self._on_money_loaded)

    def _on_money_loaded(self, rows: list[Any]):
        self._balance_loading = False
        rub_available = 0.0
        for row in rows:
            cur = str(getattr(row, "currency", "")).lower()
            if cur == "rub":
                rub_available += float(getattr(row, "available", 0.0) or 0.0)
        self.lbl_balance.setText(f"Доступно RUB: {rub_available:,.2f}".replace(",", " "))

    def request_status_refresh(self):
        if not self._check_refresh_rate_limit():
            return
        now = datetime.now()
        if self._last_status_refresh_time is not None:
            elapsed_ms = (now - self._last_status_refresh_time).total_seconds() * 1000
            if elapsed_ms < self.MIN_STATUS_REFRESH_INTERVAL_MS:
                return
        if self._updating:
            _log("request_status_refresh SKIP: already updating")
            return
        if not self._status_lock.tryLock(0):
            _log("request_status_refresh SKIP: status_lock busy")
            self._status_cycle_pending = True
            return
        try:
            if self._status_cycle_running:
                _log("request_status_refresh SKIP: cycle running")
                self._status_cycle_pending = True
                return
            self._status_cycle_running = True
            self._status_cycle_pending = False
        finally:
            self._status_lock.unlock()
        _log(f"request_status_refresh #{self._refresh_count}")
        self._last_status_refresh_time = now
        self.refresh_statuses()

    def refresh_statuses(self):
        _log("refresh_statuses START")

        # ✅ ПРОВЕРКА: Предыдущие загрузки ещё не завершены?
        if self._active_loading or self._deals_loading or self._order_state_loading:
            _log("refresh_statuses SKIP: previous loads still in progress")
            return

        if not self.isVisible():
            _log("refresh_statuses SKIP: not visible")
            return
        if self._updating:
            _log("refresh_statuses SKIP: already updating")
            return
        self._updating = True
        try:
            _log("refresh_statuses: polling orders")
            self.poll_active_orders()
            if self._deals_enabled:
                _log("refresh_statuses: refreshing deals")
                self._refresh_recent_deals()
            _log("refresh_statuses: FINISH")
            self._try_finish_status_cycle()
        except Exception as e:
            _log(f"refresh_statuses ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            sys.stdout.flush()
            self._try_finish_status_cycle()
        finally:
            self._updating = False

    def _try_finish_status_cycle(self):
        _log(
            f"_try_finish_status_cycle: active={self._active_loading}, deals={self._deals_loading}, states={self._order_state_loading}")

        # ✅ ПРОВЕРКА: Все ли загрузки завершены?
        still_loading = self._active_loading or self._deals_loading or self._order_state_loading
        if still_loading:
            _log("_try_finish_status_cycle: SKIP - still loading")
            return

        # ✅ Загрузки завершены - блокируем и планируем рендер
        if not self._status_lock.tryLock(0):
            _log("_try_finish_status_cycle: lock busy")
            return

        try:
            if self._status_cycle_pending:
                _log("_try_finish_status_cycle: pending - restarting cycle")
                self._status_cycle_pending = False
                self._status_cycle_running = True
                QtCore.QTimer.singleShot(0, self.refresh_statuses)
            else:
                if self._status_cycle_running:
                    _log("_try_finish_status_cycle: FINISHED - scheduling render")
                    self._status_cycle_running = False
                # ✅ ВСЕГДА планируем рендер когда загрузки завершены
                QtCore.QTimer.singleShot(100, self._request_render)
        finally:
            self._status_lock.unlock()

    def _refresh_recent_deals(self):
        if not self._account_id or self._deals_loading:
            return
        self._deals_loading = True
        from_dt = datetime.now(timezone.utc) - timedelta(days=3)
        worker = RecentDealsLoader(TOKEN, self._account_id, from_dt)
        self._run_worker(worker, self._on_recent_deals_loaded)

    def _on_recent_deals_loaded(self, payload: dict[str, Any]):
        self._deals_loading = False
        _log("_on_recent_deals_loaded: START")
        error = str(payload.get("error", "") or "")
        if error == "UNAUTHENTICATED":
            self._deals_enabled = False
            self.lbl_status.setText("История сделок временно отключена: UNAUTHENTICATED")
            self._try_finish_status_cycle()
            return
        deals = payload.get("rows", []) or []
        if deals:
            merged = self._merge_fills(self._fills_cache, deals)
            self._fills_cache = self._keep_last_3_days(merged)
            self._save_fills_cache()
        self._sync_orders_with_fills()
        _log("_on_recent_deals_loaded: calling _try_finish_status_cycle")
        self._try_finish_status_cycle()
        _log("_on_recent_deals_loaded: scheduling picker.refresh_quantities")
        QtCore.QTimer.singleShot(500, self.picker.refresh_quantities)
        # ✅ УБРАЛИ _request_render - он вызывается в _try_finish_status_cycle
        _log("_on_recent_deals_loaded: DONE")

    def poll_active_orders(self):
        if not self.isVisible():
            _log("poll_active_orders SKIP: not visible")
            return
        if not self._account_id:
            _log("poll_active_orders SKIP: no account_id")
            return
        if self._active_loading:
            _log("poll_active_orders SKIP: already loading")
            return
        if self._orders_poll_blocked_until is not None:
            if datetime.now(timezone.utc) < self._orders_poll_blocked_until:
                _log("poll_active_orders SKIP: rate limited")
                return
            self._orders_poll_blocked_until = None
        _log("poll_active_orders: START")
        self._active_loading = True
        worker = SandboxActiveOrdersLoader(TOKEN, self._account_id)
        self._run_worker(worker, self._on_active_orders_loaded)

    def _on_active_orders_loaded(self, orders: list[ActiveOrder]):
        self._active_loading = False
        _log(f"_on_active_orders_loaded: {len(orders)} orders")
        try:
            self._server_active_by_id = {o.order_id: o for o in orders if o.order_id}
            _log("_on_active_orders_loaded: rendering server orders table")
            self._render_server_orders_table()
            _log("_on_active_orders_loaded: calling _sync_orders_with_server")
            self._sync_orders_with_server()
            _log("_on_active_orders_loaded: calling _try_finish_status_cycle")
            self._try_finish_status_cycle()
            _log("_on_active_orders_loaded: DONE")
        except Exception as e:
            _log(f"_on_active_orders_loaded ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            sys.stdout.flush()
            self._try_finish_status_cycle()

    def _place_limit(self, side: str):
        if not self._account_id:
            self.lbl_status.setText("Нет sandbox account_id")
            return
        if not self._selected_instrument:
            self.lbl_status.setText("Выбери инструмент")
            return
        info = self._selected_instrument
        if not info.figi:
            self.lbl_status.setText("Нет FIGI у инструмента")
            return
        try:
            lots = int(self.ed_lots.text().strip())
            if lots <= 0:
                raise ValueError
        except Exception:
            self.lbl_status.setText("Lots должно быть целым > 0")
            return
        price_str = self.ed_price.text().strip()
        self.lbl_status.setText(f"Отправляю {side} LIMIT {lots} lot @ {price_str} ...")
        worker = SandboxPostLimitOrderLoader(TOKEN, self._account_id, info.figi, side, lots, price_str)
        self._run_worker(worker,
                         lambda res, _info=info, _lots=lots, _p=price_str, _side=side: self._on_limit_result(res, _info,
                                                                                                             _side,
                                                                                                             _lots, _p))

    def _on_limit_result(self, res: PlaceOrderAttempt, info: InstrumentInfo, side: str, lots: int, price_str: str):
        self.lbl_status.setText(f"{res.message} (order_id={res.order_id})")
        self._add_local_order(info=info, side=side, order_type="LIMIT", lots=lots, price=price_str, sent=bool(res.sent),
                              order_id=res.order_id, message=res.message)
        if res.sent:
            QtCore.QTimer.singleShot(250, self.request_status_refresh)
            QtCore.QTimer.singleShot(300, self.refresh_balance)
            QtCore.QTimer.singleShot(450, self.picker.refresh_quantities)
        else:
            self._request_render()

    def _add_local_order(self, *, info: InstrumentInfo, side: str, order_type: str, lots: int, price: str, sent: bool,
                         order_id: str, message: str):
        now = datetime.now(timezone.utc).isoformat()
        rec = {"local_id": str(uuid.uuid4()), "account_id": self._account_id, "figi": info.figi, "ticker": info.ticker,
               "side": side, "order_type": order_type, "lots_requested": int(lots), "lots_executed": 0, "price": price,
               "order_id": order_id or "", "server_status": "",
               "status_ui": "Активна" if sent and order_id else "Не активна", "message": message, "created_at": now}
        self._orders_cache.append(rec)
        self._save_orders_cache()

    def _load_orders_cache(self) -> list[dict[str, Any]]:
        """Загрузить ордера из базы данных или JSON."""
        if DB_ENABLED and OrderRepository is not None:
            try:
                orders = OrderRepository.get_all(self._account_id)
                result = [o.to_dict() for o in orders]
                _log(f"Loaded {len(result)} orders from DB")
                return result
            except Exception as e:
                _log(f"DB load orders ERROR: {e}")

        # Fallback to JSON
        path = Path(self.ORDERS_CACHE_FILE)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload.get("orders", [])
            return [x for x in items if isinstance(x, dict)]
        except Exception:
            return []

    def _save_orders_cache(self):
        """Сохранить ордера в базу данных и JSON."""
        if DB_ENABLED and OrderRepository is not None:
            try:
                # Сохраняем последний ордер в БД
                if self._orders_cache:
                    last_order = self._orders_cache[-1]
                    order = Order.from_dict(last_order)
                    OrderRepository.insert(order)
                _log("Saved order to DB")
            except Exception as e:
                _log(f"DB save order ERROR: {e}")

        # Fallback to JSON
        path = Path(self.ORDERS_CACHE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"orders": self._orders_cache}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_fills_cache(self) -> list[dict[str, Any]]:
        """Загрузить исполнения из базы данных или JSON."""
        if DB_ENABLED and FillRepository is not None:
            try:
                fills = FillRepository.get_all(self._account_id, days=3)
                result = [f.to_dict() for f in fills]
                _log(f"Loaded {len(result)} fills from DB")
                return result
            except Exception as e:
                _log(f"DB load fills ERROR: {e}")

        # Fallback to JSON
        path = Path(self.FILLS_CACHE_FILE)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload.get("fills", [])
            return [x for x in items if isinstance(x, dict)]
        except Exception:
            return []

    def _save_fills_cache(self):
        """Сохранить исполнения в базу данных и JSON."""
        if DB_ENABLED and FillRepository is not None:
            try:
                fills = [Fill.from_dict(f) for f in self._fills_cache if isinstance(f, dict)]
                FillRepository.insert_many(fills)
                _log(f"Saved {len(fills)} fills to DB")
            except Exception as e:
                _log(f"DB save fills ERROR: {e}")

        # Fallback to JSON
        path = Path(self.FILLS_CACHE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fills": self._fills_cache}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ui_status(self, server_status: str, on_server: bool, lots_req: int = 0, lots_exec: int = 0) -> str:
        if not on_server:
            return "Не активна"
        s = (server_status or "").upper().replace("EXECUTION_REPORT_STATUS_", "")
        numeric_map = {"0": "Не активна", "1": "Исполнена", "2": "Отклонена", "3": "Отменена", "4": "Активна",
                       "5": "Частично исполнена", "6": "Активна"}
        if s in numeric_map:
            return numeric_map[s]
        if "PARTIALLY" in s:
            return "Частично исполнена"
        if "FILL" in s:
            return "Исполнена"
        if "CANCEL" in s:
            return "Отменена"
        if "REJECT" in s:
            return "Отклонена"
        if "NEW" in s or "ACTIVE" in s:
            return "Активна"
        return str(server_status) if str(server_status).strip() else "Активна"

    def _sync_orders_with_server(self):
        _log(f"_sync_orders_with_server: {len(self._orders_cache)} orders in cache")
        changed = False
        order_ids_to_check: list[str] = []
        fills_to_append: list[dict[str, Any]] = []
        for rec in self._orders_cache:
            if rec.get("account_id") != self._account_id:
                continue
            order_id = str(rec.get("order_id", "") or "")
            if not order_id:
                if rec.get("status_ui") != "Не активна":
                    rec["status_ui"] = "Не активна"
                    changed = True
                continue
            srv = self._server_active_by_id.get(order_id)
            if srv is None:
                if self._order_state_enabled and rec.get("status_ui") not in ("Исполнена", "Отменена", "Отклонена"):
                    order_ids_to_check.append(order_id)
                elif rec.get("status_ui") not in ("Исполнена", "Отменена", "Отклонена"):
                    rec["status_ui"] = "Не активна"
                    changed = True
                continue
            new_server_status = str(srv.status)
            new_lots_exec = int(srv.lots_executed)
            req_lots = int(rec.get("lots_requested", 0) or 0)
            new_status_ui = self._ui_status(new_server_status, True, req_lots, new_lots_exec)
            if rec.get("server_status") != new_server_status:
                rec["server_status"] = new_server_status
                changed = True
            if rec.get("status_ui") != new_status_ui:
                rec["status_ui"] = new_status_ui
                changed = True
            if int(rec.get("lots_executed", 0) or 0) != new_lots_exec:
                rec["lots_executed"] = new_lots_exec
                changed = True
            if new_status_ui == "Исполнена":
                fill = self._build_fill_from_order(rec, source="server-status")
                if fill is not None:
                    fills_to_append.append(fill)
                    changed = True
        if fills_to_append:
            _log(f"_sync_orders_with_server: appending {len(fills_to_append)} fills")
            self._append_fills(fills_to_append)
        if changed:
            _log("_sync_orders_with_server: saving cache")
            self._save_orders_cache()
        if order_ids_to_check:
            _log(f"_sync_orders_with_server: requesting states for {len(order_ids_to_check)} orders")
            self._request_order_states(order_ids_to_check)
        _log("_sync_orders_with_server: DONE")

    def _build_fill_from_order(self, rec: dict[str, Any], source: str) -> Optional[dict[str, Any]]:
        order_id = str(rec.get("order_id", "") or "")
        if not order_id:
            return None
        return {"deal_id": f"order:{order_id}", "account_id": rec.get("account_id", ""),
                "time": datetime.now(timezone.utc).isoformat(), "figi": rec.get("figi", ""),
                "ticker": rec.get("ticker", ""), "side": rec.get("side", ""), "order_type": rec.get("order_type", ""),
                "lots": rec.get("lots_executed", rec.get("lots_requested", 0)), "price": rec.get("price", ""),
                "status": "Исполнена", "order_id": order_id, "source": source}

    def _append_fills(self, fills: list[dict[str, Any]]):
        if not fills:
            return
        self._fills_cache = self._merge_fills(self._fills_cache, fills)
        self._fills_cache = self._keep_last_3_days(self._fills_cache)
        self._save_fills_cache()

    def _request_order_states(self, order_ids: list[str]):
        if not self._account_id or self._order_state_loading or not order_ids:
            return
        unique_ids = sorted(set([x for x in order_ids if x]))
        if not unique_ids:
            return
        self._order_state_loading = True
        worker = OrderStatesLoader(TOKEN, self._account_id, unique_ids)
        self._run_worker(worker, self._on_order_states_loaded)

    def _on_order_states_loaded(self, payload: dict[str, Any]):
        self._order_state_loading = False
        error = str(payload.get("error", "") or "")
        states: dict[str, str] = payload.get("states", {}) or {}
        if error == "UNAUTHENTICATED":
            self._order_state_enabled = False
            return
        changed = False
        fills_to_append: list[dict[str, Any]] = []
        for rec in self._orders_cache:
            if rec.get("account_id") != self._account_id:
                continue
            oid = str(rec.get("order_id", "") or "")
            if not oid or rec.get("status_ui") in ("Исполнена", "Отменена", "Отклонена"):
                continue
            state_status = str(states.get(oid, "") or "")
            if state_status:
                req_lots = int(rec.get("lots_requested", 0) or 0)
                exec_lots = int(rec.get("lots_executed", 0) or 0)
                new_status_ui = self._ui_status(state_status, True, req_lots, exec_lots)
                if rec.get("server_status") != state_status:
                    rec["server_status"] = state_status
                    changed = True
                if rec.get("status_ui") != new_status_ui:
                    rec["status_ui"] = new_status_ui
                    changed = True
                if new_status_ui == "Исполнена":
                    fill = self._build_fill_from_order(rec, source="order-state")
                    if fill is not None:
                        fills_to_append.append(fill)
                        changed = True
            else:
                if rec.get("status_ui") != "Не активна":
                    rec["status_ui"] = "Не активна"
                    changed = True
        if fills_to_append:
            self._append_fills(fills_to_append)
        if changed:
            self._save_orders_cache()
        self._sync_orders_with_fills()
        self._request_render()
        self._try_finish_status_cycle()

    def _request_render(self):
        _log("_request_render: START")
        now = datetime.now()
        if self._last_render_time is not None:
            elapsed_ms = (now - self._last_render_time).total_seconds() * 1000
            if elapsed_ms < 200:
                _log(f"_request_render: SKIP debounce ({elapsed_ms:.0f}ms)")
                if not self._render_scheduled:
                    QtCore.QTimer.singleShot(200, self._request_render)
                return
        if self._render_scheduled:
            _log("_request_render: SKIP already scheduled")
            return
        self._render_scheduled = True
        _log("_request_render: scheduling _render_tables")
        QtCore.QTimer.singleShot(0, self._render_tables)

    def _sync_orders_with_fills(self):
        fills_by_order_id = {str(x.get("order_id", "") or ""): x for x in self._fills_cache if x.get("order_id")}
        changed = False
        for rec in self._orders_cache:
            oid = str(rec.get("order_id", "") or "")
            if not oid:
                continue
            if oid in fills_by_order_id:
                if rec.get("status_ui") != "Исполнена":
                    rec["status_ui"] = "Исполнена"
                    changed = True
        if changed:
            self._save_orders_cache()

    def _merge_fills(self, old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}

        def _key(x: dict[str, Any]) -> str:
            return str(x.get("deal_id") or x.get("order_id") or f"{x.get('time')}|{x.get('figi')}|{x.get('price')}")

        for row in old_rows:
            by_key[_key(row)] = row
        for row in new_rows:
            by_key[_key(row)] = row
        return list(by_key.values())

    def _keep_last_3_days(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        out: list[dict[str, Any]] = []
        for row in rows:
            t = self._parse_dt(row.get("time"))
            if t is None or t >= cutoff:
                out.append(row)
        out.sort(key=lambda x: str(x.get("time", "")), reverse=True)
        return out

    def _parse_dt(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    def _render_tables(self):
        self._render_scheduled = False
        if self._is_rendering_tables or not self.isVisible():
            return
        now = datetime.now()
        if self._last_render_time is not None:
            elapsed_ms = (now - self._last_render_time).total_seconds() * 1000
            if elapsed_ms < 200:
                return
        _log(f"_render_tables START")
        self._last_render_time = now
        self._is_rendering_tables = True

        selected_figi = ""
        if self.cb_only_selected.isChecked():
            if self._selected_instrument is None:
                selected_figi = "__NO_SELECTION__"
            else:
                selected_figi = self._selected_instrument.figi

        active_rows = []
        for rec in self._orders_cache:
            if rec.get("account_id") != self._account_id:
                continue
            if rec.get("status_ui") == "Исполнена":
                continue
            if selected_figi and rec.get("figi") != selected_figi:
                continue
            active_rows.append(rec)
        if len(active_rows) > self.MAX_ACTIVE_ROWS_RENDER:
            active_rows = active_rows[: self.MAX_ACTIVE_ROWS_RENDER]

        history_rows = []
        for rec in self._fills_cache:
            if rec.get("account_id") != self._account_id:
                continue
            if selected_figi and rec.get("figi") != selected_figi:
                continue
            history_rows.append(rec)
            if len(history_rows) >= self.MAX_HISTORY_ROWS_RENDER:
                break

        try:
            self.tbl_active.setUpdatesEnabled(False)
            self.tbl_history.setUpdatesEnabled(False)
            self.tbl_active.blockSignals(True)
            self.tbl_history.blockSignals(True)
            self.tbl_active.setRowCount(0)
            self.tbl_history.setRowCount(0)

            self.tbl_active.setRowCount(len(active_rows))
            for r, rec in enumerate(active_rows):
                self.tbl_active.setItem(r, 0, QtWidgets.QTableWidgetItem(str(rec.get("order_id", ""))))
                self.tbl_active.setItem(r, 1, QtWidgets.QTableWidgetItem(str(rec.get("ticker", ""))))
                self.tbl_active.setItem(r, 2, QtWidgets.QTableWidgetItem(str(rec.get("side", ""))))
                self.tbl_active.setItem(r, 3, QtWidgets.QTableWidgetItem(str(rec.get("order_type", ""))))
                self.tbl_active.setItem(r, 4, QtWidgets.QTableWidgetItem(str(rec.get("lots_requested", ""))))
                self.tbl_active.setItem(r, 5, QtWidgets.QTableWidgetItem(str(rec.get("lots_executed", ""))))
                self.tbl_active.setItem(r, 6, QtWidgets.QTableWidgetItem(str(rec.get("price", ""))))
                self.tbl_active.setItem(r, 7, QtWidgets.QTableWidgetItem(str(rec.get("status_ui", ""))))
                del_item = QtWidgets.QTableWidgetItem("Удалить")
                del_item.setData(QtCore.Qt.ItemDataRole.UserRole, str(rec.get("local_id", "")))
                self.tbl_active.setItem(r, 8, del_item)

            self.tbl_history.setRowCount(len(history_rows))
            for r, rec in enumerate(history_rows):
                self.tbl_history.setItem(r, 0, QtWidgets.QTableWidgetItem(str(rec.get("time", ""))))
                self.tbl_history.setItem(r, 1, QtWidgets.QTableWidgetItem(str(rec.get("ticker", ""))))
                self.tbl_history.setItem(r, 2, QtWidgets.QTableWidgetItem(str(rec.get("side", ""))))
                self.tbl_history.setItem(r, 3, QtWidgets.QTableWidgetItem(str(rec.get("order_type", ""))))
                self.tbl_history.setItem(r, 4, QtWidgets.QTableWidgetItem(str(rec.get("lots", ""))))
                self.tbl_history.setItem(r, 5, QtWidgets.QTableWidgetItem(str(rec.get("price", ""))))
                self.tbl_history.setItem(r, 6, QtWidgets.QTableWidgetItem(str(rec.get("status", "Исполнена"))))
                self.tbl_history.setItem(r, 7, QtWidgets.QTableWidgetItem(str(rec.get("order_id", ""))))
                self.tbl_history.setItem(r, 8, QtWidgets.QTableWidgetItem(str(rec.get("source", "cache"))))
        except Exception as e:
            _log(f"_render_tables ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            sys.stdout.flush()
        finally:
            self.tbl_active.blockSignals(False)
            self.tbl_history.blockSignals(False)
            self.tbl_active.setUpdatesEnabled(True)
            self.tbl_history.setUpdatesEnabled(True)
            self.tbl_active.viewport().update()
            self.tbl_history.viewport().update()
            self._is_rendering_tables = False
            _log(f"_render_tables DONE: {len(active_rows)} active, {len(history_rows)} history")

    def _delete_order(self, local_id: str):
        rec = next((x for x in self._orders_cache if str(x.get("local_id", "")) == local_id), None)
        if rec is None:
            return
        order_id = str(rec.get("order_id", "") or "")
        if order_id and self._account_id:
            worker = CancelSandboxOrderWorker(TOKEN, self._account_id, order_id)
            self._run_worker(worker, lambda *_: self._remove_local_order(local_id))
            return
        self._remove_local_order(local_id)

    def _delete_server_order(self, order_id: str):
        """✅ Удаление ордера с сервера."""
        if not order_id or not self._account_id:
            _log(f"_delete_server_order: SKIP - no order_id or account_id")
            return

        _log(f"_delete_server_order: cancelling {order_id}")
        self.lbl_status.setText(f"Отмена ордера {order_id[:8]}...")

        worker = CancelSandboxOrderWorker(TOKEN, self._account_id, order_id)
        self._run_worker(worker, lambda *_: self._on_server_order_cancelled(order_id))

    def _on_server_order_cancelled(self, order_id: str):
        """✅ Обработка успешной отмены ордера."""
        _log(f"_on_server_order_cancelled: {order_id}")
        self.lbl_status.setText(f"Ордер {order_id[:8]} отменён")

        # ✅ Удаляем из локального кэша
        self._orders_cache = [x for x in self._orders_cache if str(x.get("order_id", "")) != order_id]
        self._save_orders_cache()

        # ✅ Удаляем из серверного словаря
        if order_id in self._server_active_by_id:
            del self._server_active_by_id[order_id]

        # ✅ Перерисовываем обе таблицы
        self._request_render()
        self._render_server_orders_table()

    def _remove_local_order(self, local_id: str):
        self._orders_cache = [x for x in self._orders_cache if str(x.get("local_id", "")) != local_id]

        # Удаляем из БД
        if DB_ENABLED and OrderRepository is not None:
            try:
                OrderRepository.delete_by_local_id(local_id)
                _log(f"Deleted order {local_id} from DB")
            except Exception as e:
                _log(f"DB delete ERROR: {e}")

        self._save_orders_cache()
        self._request_render()

    def _on_active_cell_clicked(self, row: int, column: int):
        if column != 8:
            return
        item = self.tbl_active.item(row, 8)
        if item is None:
            return
        local_id = str(item.data(QtCore.Qt.ItemDataRole.UserRole) or "")
        if local_id:
            self._delete_order(local_id)

    def _on_server_order_cell_clicked(self, row: int, column: int):
        """✅ Обработка клика по кнопке 'Удалить' во второй таблице."""
        if column != 8:
            return
        item = self.tbl_server_orders.item(row, 0)  # order_id в первой колонке
        if item is None:
            return
        order_id = str(item.text())
        if order_id:
            _log(f"_on_server_order_cell_clicked: deleting order {order_id}")
            self._delete_server_order(order_id)

    def _refresh_server_orders_manual(self):
        """✅ Ручное обновление серверных ордеров по кнопке."""
        _log("_refresh_server_orders_manual: START")
        self.lbl_server_orders_count.setText("Загрузка...")
        self.poll_active_orders()

    def _render_server_orders_table(self):
        """✅ Отрисовка таблицы серверных ордеров."""
        try:
            _log(f"_render_server_orders_table: {len(self._server_active_by_id)} orders")

            # ✅ Обновляем _by_figi если пустой
            if not self._by_figi:
                _log("_render_server_orders_table: _by_figi is empty, calling _reindex_figi")
                self._reindex_figi()

            self.tbl_server_orders.setUpdatesEnabled(False)
            self.tbl_server_orders.blockSignals(True)
            self.tbl_server_orders.setRowCount(0)

            orders_list = list(self._server_active_by_id.values())
            self.tbl_server_orders.setRowCount(len(orders_list))

            for r, order in enumerate(orders_list):
                # ✅ Ищем тикер: сначала в _by_figi, потом в кэше ордеров
                ticker = ""
                if order.figi and order.figi in self._by_figi:
                    ticker = self._by_figi[order.figi].ticker
                else:
                    # Ищем в кэше ордеров по FIGI
                    for rec in self._orders_cache:
                        if rec.get("figi") == order.figi:
                            ticker = rec.get("ticker", "")
                            break

                if not ticker:
                    ticker = order.figi  # Fallback к FIGI

                self.tbl_server_orders.setItem(r, 0, QtWidgets.QTableWidgetItem(str(order.order_id)))
                self.tbl_server_orders.setItem(r, 1, QtWidgets.QTableWidgetItem(ticker))
                self.tbl_server_orders.setItem(r, 2, QtWidgets.QTableWidgetItem(str(order.direction)))
                self.tbl_server_orders.setItem(r, 3, QtWidgets.QTableWidgetItem(str(order.order_type)))
                self.tbl_server_orders.setItem(r, 4, QtWidgets.QTableWidgetItem(str(order.lots_requested)))
                self.tbl_server_orders.setItem(r, 5, QtWidgets.QTableWidgetItem(str(order.lots_executed)))
                self.tbl_server_orders.setItem(r, 6, QtWidgets.QTableWidgetItem(str(order.price)))

                status_ui = self._ui_status(order.status, True, order.lots_requested, order.lots_executed)
                self.tbl_server_orders.setItem(r, 7, QtWidgets.QTableWidgetItem(status_ui))

                # ✅ Кнопка "Удалить"
                del_item = QtWidgets.QTableWidgetItem("❌")
                del_item.setToolTip("Удалить ордер")
                del_item.setFlags(del_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                self.tbl_server_orders.setItem(r, 8, del_item)

            self.lbl_server_orders_count.setText(f"Активные ордера на сервере: {len(orders_list)}")

        except Exception as e:
            _log(f"_render_server_orders_table ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            sys.stdout.flush()
        finally:
            self.tbl_server_orders.blockSignals(False)
            self.tbl_server_orders.setUpdatesEnabled(True)
            self.tbl_server_orders.viewport().update()

    def _get_ticker_by_figi(self, figi: str) -> str:
        """✅ Получить тикер по FIGI."""
        _log(f"_get_ticker_by_figi: looking for {figi}, _by_figi has {len(self._by_figi)} items")

        if figi in self._by_figi:
            ticker = self._by_figi[figi].ticker
            _log(f"_get_ticker_by_figi: found in _by_figi: {ticker}")
            return ticker

        # Ищем в кэше ордеров
        for rec in self._orders_cache:
            if rec.get("figi") == figi:
                ticker = rec.get("ticker", figi)
                _log(f"_get_ticker_by_figi: found in orders_cache: {ticker}")
                return ticker

        _log(f"_get_ticker_by_figi: NOT FOUND, returning figi: {figi}")
        return figi
