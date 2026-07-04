from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import uuid
from typing import Optional, Any

from PyQt6 import QtCore, QtWidgets
from t_tech.invest import Client

from app.config import TOKEN, DATA_DIR
from core.instruments_catalog import InstrumentInfo
from tabs.instruments_controller import InstrumentsController
from tabs.quotes_hub import QuotesHub
from tabs.trading_context import TradingContext
from tabs.instrument_picker_widget import kind_to_short
from tabs.sandbox_favorites_picker import FavoritesOnlyPicker
from tabs.sandbox_trading_service_workers import (
    CancelSandboxOrderWorker,
    OrderStatesLoader,
    RecentDealsLoader,
    make_request_for_method,
    set_req_attr,
)

from core.sandbox_orders_api import PlaceOrderAttempt, ActiveOrder
from tabs.workers import SandboxAccountsLoader, SandboxMoneyBalanceLoader

try:
    from tabs.workers import SandboxPostLimitOrderLoader, SandboxActiveOrdersLoader
except Exception:
    SandboxPostLimitOrderLoader = None  # type: ignore
    SandboxActiveOrdersLoader = None  # type: ignore
    from core.sandbox_orders_api import try_post_sandbox_limit_order, list_active_sandbox_orders

    class _LocalPostLimitOrderWorker(QtCore.QObject):
        loaded = QtCore.pyqtSignal(object)
        error = QtCore.pyqtSignal(str)
        finished = QtCore.pyqtSignal()

        def __init__(self, token: str, account_id: str, figi: str, direction: str, lots: int, price_str: str):
            super().__init__()
            self.token = token
            self.account_id = account_id
            self.figi = figi
            self.direction = direction
            self.lots = lots
            self.price_str = price_str

        @QtCore.pyqtSlot()
        def run(self):
            try:
                res = try_post_sandbox_limit_order(
                    self.token,
                    self.account_id,
                    figi=self.figi,
                    direction=self.direction,
                    lots=self.lots,
                    price_str=self.price_str,
                )
                self.loaded.emit(res)
            except Exception:
                import traceback

                self.error.emit(traceback.format_exc())
            finally:
                self.finished.emit()

    class _LocalActiveOrdersWorker(QtCore.QObject):
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
                res = list_active_sandbox_orders(self.token, self.account_id)
                self.loaded.emit(res)
            except Exception:
                import traceback

                self.error.emit(traceback.format_exc())
            finally:
                self.finished.emit()


class SandboxTradingTab(QtWidgets.QWidget):
    ORDERS_CACHE_FILE = DATA_DIR / "orders_cache.json"
    FILLS_CACHE_FILE = DATA_DIR / "fills_cache.json"

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
        self.picker = FavoritesOnlyPicker(controller=self.instr_controller, quotes_hub=self.quotes_hub, parent=self)

        self._selected_instrument: Optional[InstrumentInfo] = None
        self._account_id: str = ""

        self._by_figi: dict[str, InstrumentInfo] = {}

        self.btn_refresh_accounts = QtWidgets.QPushButton("Обновить sandbox аккаунты")
        self.cb_accounts = QtWidgets.QComboBox()
        self.cb_accounts.setMinimumWidth(260)
        self.lbl_balance = QtWidgets.QLabel("Доступно RUB: -")

        self.lbl_selected = QtWidgets.QLabel("Инструмент: не выбран")
        self.lbl_selected.setWordWrap(True)

        self.ed_lots = QtWidgets.QLineEdit("1")
        self.ed_lots.setMaximumWidth(70)
        self.ed_price = QtWidgets.QLineEdit("250.00")
        self.ed_price.setMaximumWidth(110)

        self.btn_buy_limit = QtWidgets.QPushButton("BUY LIMIT")
        self.btn_sell_limit = QtWidgets.QPushButton("SELL LIMIT")
        self.cb_only_selected = QtWidgets.QCheckBox("только выбранное")
        self.btn_refresh_status = QtWidgets.QPushButton("Обновить статус")

        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)

        self.tbl_active = QtWidgets.QTableWidget(0, 9)
        self.tbl_active.setHorizontalHeaderLabels(
            [
                "order_id",
                "Ticker",
                "Side",
                "Type",
                "Lots req",
                "Lots exec",
                "Price",
                "Status",
                "Удалить",
            ]
        )
        self.tbl_active.horizontalHeader().setStretchLastSection(True)
        self.tbl_active.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        self.tbl_history = QtWidgets.QTableWidget(0, 9)
        self.tbl_history.setHorizontalHeaderLabels(
            [
                "time",
                "Ticker",
                "Side",
                "Type",
                "Lots",
                "Price",
                "Status",
                "order_id",
                "Источник",
            ]
        )
        self.tbl_history.horizontalHeader().setStretchLastSection(True)
        self.tbl_history.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)

        acc_line = QtWidgets.QHBoxLayout()
        acc_line.addWidget(self.btn_refresh_accounts)
        acc_line.addWidget(QtWidgets.QLabel("Account:"))
        acc_line.addWidget(self.cb_accounts, 1)
        acc_line.addWidget(self.lbl_balance)

        params = QtWidgets.QHBoxLayout()
        params.addWidget(QtWidgets.QLabel("Lots:"))
        params.addWidget(self.ed_lots)
        params.addWidget(QtWidgets.QLabel("Price:"))
        params.addWidget(self.ed_price)
        params.addStretch()

        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(self.btn_buy_limit)
        btns.addWidget(self.btn_sell_limit)
        btns.addStretch()

        order_tools = QtWidgets.QHBoxLayout()
        order_tools.addWidget(self.cb_only_selected)
        order_tools.addWidget(self.btn_refresh_status)
        order_tools.addStretch()

        right_layout.addLayout(acc_line)
        right_layout.addWidget(self.lbl_selected)
        right_layout.addLayout(params)
        right_layout.addLayout(btns)
        right_layout.addLayout(order_tools)
        right_layout.addWidget(self.lbl_status)

        split_right = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        split_right.addWidget(self.tbl_active)
        split_right.addWidget(self.tbl_history)
        split_right.setStretchFactor(0, 2)
        split_right.setStretchFactor(1, 2)

        right_layout.addWidget(split_right)

        main_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        main_split.addWidget(self.picker)
        main_split.addWidget(right_panel)
        main_split.setStretchFactor(0, 5)
        main_split.setStretchFactor(1, 5)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(main_split)

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

        self.picker.instrument_selected.connect(self._on_instrument_selected)

        self.btn_refresh_accounts.clicked.connect(self.refresh_accounts)
        self.cb_accounts.currentIndexChanged.connect(self._on_account_changed)

        self.btn_buy_limit.clicked.connect(lambda: self._place_limit("BUY"))
        self.btn_sell_limit.clicked.connect(lambda: self._place_limit("SELL"))
        self.cb_only_selected.toggled.connect(lambda *_: self._render_tables())
        self.btn_refresh_status.clicked.connect(self.refresh_statuses)
        self.tbl_active.cellClicked.connect(self._on_active_cell_clicked)

        self.instr_controller.shares_updated.connect(self._reindex_figi)
        self.instr_controller.bonds_updated.connect(self._reindex_figi)
        self.instr_controller.etfs_updated.connect(self._reindex_figi)

        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self.poll_active_orders)
        self._poll_timer.start()

        self._render_tables()
        QtCore.QTimer.singleShot(0, self.refresh_accounts)

    def stop(self):
        self._poll_timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def hideEvent(self, event):
        self._poll_timer.stop()
        super().hideEvent(event)

    def _reindex_figi(self, *_):
        self._by_figi = {}
        for info in self.instr_controller.favorites():
            if info.figi:
                self._by_figi[info.figi] = info

    def _run_worker(self, worker: QtCore.QObject, on_loaded=None):
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)

        if hasattr(worker, "loaded") and on_loaded is not None:
            worker.loaded.connect(on_loaded)

        if hasattr(worker, "error"):
            worker.error.connect(self._on_worker_error)

        if hasattr(worker, "finished"):
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)

        thread.started.connect(worker.run)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._cleanup_job(t))

        self._jobs.append((thread, worker))
        thread.start()

    def _cleanup_job(self, thread: QtCore.QThread):
        self._jobs = [(t, w) for (t, w) in self._jobs if t is not thread]

    def _on_worker_error(self, tb: str):
        self._active_loading = False
        self._balance_loading = False
        self._deals_loading = False
        self._order_state_loading = False

        if "RESOURCE_EXHAUSTED" in tb and "GetSandboxOrders" in tb:
            wait_sec = self._extract_ratelimit_reset(tb)
            self._orders_poll_blocked_until = datetime.now(timezone.utc) + timedelta(seconds=wait_sec)
            self.lbl_status.setText(f"Лимит API по заявкам исчерпан, ждем {wait_sec} сек")
            return

        self.lbl_status.setText("Ошибка (см. консоль)")
        print("===== ERROR (SandboxTradingTab) =====")
        print(tb)
        print("=====================================")

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
        self._render_tables()

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
            self.refresh_statuses()
        else:
            self._account_id = ""
            self.lbl_balance.setText("Доступно RUB: -")
            self.lbl_status.setText("Аккаунтов: 0 (создай в вкладке Sandbox счёт)")
            self._render_tables()

    def _on_account_changed(self):
        self._account_id = str(self.cb_accounts.currentData() or "")
        self.trading_context.set_account_id(self._account_id)
        self.refresh_balance()
        self.refresh_statuses()

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

    def refresh_statuses(self):
        self.poll_active_orders()
        if self._deals_enabled:
            self._refresh_recent_deals()

    def _refresh_recent_deals(self):
        if not self._account_id or self._deals_loading:
            return

        self._deals_loading = True
        from_dt = datetime.now(timezone.utc) - timedelta(days=3)
        worker = RecentDealsLoader(TOKEN, self._account_id, from_dt)
        self._run_worker(worker, self._on_recent_deals_loaded)

    def _on_recent_deals_loaded(self, payload: dict[str, Any]):
        self._deals_loading = False

        error = str(payload.get("error", "") or "")
        if error == "UNAUTHENTICATED":
            self._deals_enabled = False
            self.lbl_status.setText("История сделок временно отключена: UNAUTHENTICATED")
            return

        deals = payload.get("rows", []) or []

        if deals:
            merged = self._merge_fills(self._fills_cache, deals)
            self._fills_cache = self._keep_last_3_days(merged)
            self._save_fills_cache()

        self._sync_orders_with_fills()
        self._render_tables()

    def poll_active_orders(self):
        if not self.isVisible():
            return
        if not self._account_id:
            return
        if self._active_loading:
            return
        if self._orders_poll_blocked_until is not None:
            if datetime.now(timezone.utc) < self._orders_poll_blocked_until:
                return
            self._orders_poll_blocked_until = None
        self._active_loading = True

        if SandboxActiveOrdersLoader is not None:
            worker = SandboxActiveOrdersLoader(TOKEN, self._account_id)
        else:
            worker = _LocalActiveOrdersWorker(TOKEN, self._account_id)  # type: ignore[name-defined]

        self._run_worker(worker, self._on_active_orders_loaded)

    def _on_active_orders_loaded(self, orders: list[ActiveOrder]):
        self._active_loading = False
        for o in orders:
            print(
                f"[orders] id={o.order_id} figi={o.figi} status={o.status} "
                f"lots={o.lots_executed}/{o.lots_requested}"
            )
        self._server_active_by_id = {o.order_id: o for o in orders if o.order_id}
        self._sync_orders_with_server()
        self._render_tables()

    def _append_history(
        self,
        *,
        ticker: str,
        side: str,
        order_type: str,
        lots: int,
        price: str,
        sent: bool,
        order_id: str,
        message: str,
    ):
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        r = self.tbl_history.rowCount()
        self.tbl_history.insertRow(r)
        self.tbl_history.setItem(r, 0, QtWidgets.QTableWidgetItem(t))
        self.tbl_history.setItem(r, 1, QtWidgets.QTableWidgetItem(ticker))
        self.tbl_history.setItem(r, 2, QtWidgets.QTableWidgetItem(side))
        self.tbl_history.setItem(r, 3, QtWidgets.QTableWidgetItem(order_type))
        self.tbl_history.setItem(r, 4, QtWidgets.QTableWidgetItem(str(lots)))
        self.tbl_history.setItem(r, 5, QtWidgets.QTableWidgetItem(price))
        self.tbl_history.setItem(r, 6, QtWidgets.QTableWidgetItem("yes" if sent else "no"))
        self.tbl_history.setItem(r, 7, QtWidgets.QTableWidgetItem(order_id))
        self.tbl_history.setItem(r, 8, QtWidgets.QTableWidgetItem(message))

    def _place_limit(self, side: str):
        if not self._account_id:
            self.lbl_status.setText("Нет sandbox account_id (создай аккаунт в вкладке Sandbox счёт)")
            return
        if not self._selected_instrument:
            self.lbl_status.setText("Выбери инструмент (двойной клик)")
            return

        info = self._selected_instrument

        if not info.figi:
            self.lbl_status.setText("У выбранного инструмента пустой FIGI - LIMIT отправить нельзя")
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

        if SandboxPostLimitOrderLoader is not None:
            worker = SandboxPostLimitOrderLoader(TOKEN, self._account_id, info.figi, side, lots, price_str)
        else:
            worker = _LocalPostLimitOrderWorker(TOKEN, self._account_id, info.figi, side, lots, price_str)  # type: ignore[name-defined]

        self._run_worker(
            worker,
            lambda res, _info=info, _lots=lots, _p=price_str, _side=side: self._on_limit_result(
                res,
                _info,
                _side,
                _lots,
                _p,
            ),
        )

    def _on_limit_result(self, res: PlaceOrderAttempt, info: InstrumentInfo, side: str, lots: int, price_str: str):
        self.lbl_status.setText(f"{res.message} (order_id={res.order_id})")

        self._add_local_order(
            info=info,
            side=side,
            order_type="LIMIT",
            lots=lots,
            price=price_str,
            sent=bool(res.sent),
            order_id=res.order_id,
            message=res.message,
        )

        if res.sent:
            QtCore.QTimer.singleShot(250, self.refresh_statuses)
            QtCore.QTimer.singleShot(300, self.refresh_balance)
        else:
            self._render_tables()

    def _add_local_order(
        self,
        *,
        info: InstrumentInfo,
        side: str,
        order_type: str,
        lots: int,
        price: str,
        sent: bool,
        order_id: str,
        message: str,
    ):
        now = datetime.now(timezone.utc).isoformat()
        rec = {
            "local_id": str(uuid.uuid4()),
            "account_id": self._account_id,
            "figi": info.figi,
            "ticker": info.ticker,
            "side": side,
            "order_type": order_type,
            "lots_requested": int(lots),
            "lots_executed": 0,
            "price": price,
            "order_id": order_id or "",
            "server_status": "",
            "status_ui": "Активна" if sent and order_id else "Не активна",
            "message": message,
            "created_at": now,
        }
        self._orders_cache.append(rec)
        self._save_orders_cache()

    def _load_orders_cache(self) -> list[dict[str, Any]]:
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
        path = Path(self.ORDERS_CACHE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"orders": self._orders_cache}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_fills_cache(self) -> list[dict[str, Any]]:
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
        path = Path(self.FILLS_CACHE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fills": self._fills_cache}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ui_status(self, server_status: str, on_server: bool, lots_req: int = 0, lots_exec: int = 0) -> str:
        if not on_server:
            return "Не активна"

        s = (server_status or "").upper()
        s = s.replace("EXECUTION_REPORT_STATUS_", "")

        numeric_map = {
            "0": "Не активна",
            "1": "Исполнена",
            "2": "Отклонена",
            "3": "Отменена",
            "4": "Активна",
            "5": "Частично исполнена",
            "6": "Активна",
        }
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
        changed = False
        order_ids_to_check: list[str] = []
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
                self._append_fill_from_order(rec, source="server-status")
                changed = True

        if changed:
            self._save_orders_cache()

        if order_ids_to_check:
            self._request_order_states(order_ids_to_check)

    def _append_fill_from_order(self, rec: dict[str, Any], source: str):
        order_id = str(rec.get("order_id", "") or "")
        if not order_id:
            return

        fill = {
            "deal_id": f"order:{order_id}",
            "account_id": rec.get("account_id", ""),
            "time": datetime.now(timezone.utc).isoformat(),
            "figi": rec.get("figi", ""),
            "ticker": rec.get("ticker", ""),
            "side": rec.get("side", ""),
            "order_type": rec.get("order_type", ""),
            "lots": rec.get("lots_executed", rec.get("lots_requested", 0)),
            "price": rec.get("price", ""),
            "status": "Исполнена",
            "order_id": order_id,
            "source": source,
        }
        self._fills_cache = self._merge_fills(self._fills_cache, [fill])
        self._fills_cache = self._keep_last_3_days(self._fills_cache)
        self._save_fills_cache()

    def _request_order_states(self, order_ids: list[str]):
        if not self._account_id or self._order_state_loading:
            return
        if not order_ids:
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
        for rec in self._orders_cache:
            if rec.get("account_id") != self._account_id:
                continue
            oid = str(rec.get("order_id", "") or "")
            if not oid:
                continue
            if rec.get("status_ui") in ("Исполнена", "Отменена", "Отклонена"):
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
                    self._append_fill_from_order(rec, source="order-state")
                    changed = True
            else:
                if rec.get("status_ui") != "Не активна":
                    rec["status_ui"] = "Не активна"
                    changed = True

        if changed:
            self._save_orders_cache()
        self._sync_orders_with_fills()
        self._render_tables()

    def _fetch_order_state_status(self, order_id: str) -> str:
        if not order_id or not self._account_id:
            return ""

        try:
            with Client(token=TOKEN) as client:
                sb = getattr(client, "sandbox", None)
                if sb is None:
                    return ""

                method = getattr(sb, "get_sandbox_order_state", None)
                if method is None:
                    method = getattr(sb, "get_sandbox_order", None)
                if method is None:
                    return ""

                try:
                    resp = method(account_id=self._account_id, order_id=order_id)
                except TypeError:
                    req = make_request_for_method(method)
                    set_req_attr(req, ["account_id", "accountId", "id"], self._account_id)
                    set_req_attr(req, ["order_id", "orderId"], order_id)
                    resp = method(request=req)

                return str(getattr(resp, "execution_report_status", "") or getattr(resp, "status", "") or "")
        except Exception as exc:
            if "UNAUTHENTICATED" in str(exc).upper():
                self._order_state_enabled = False
            return ""

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
        if self._is_rendering_tables:
            return
        self._is_rendering_tables = True
        try:
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

            self.tbl_active.setRowCount(0)
            for rec in active_rows:
                r = self.tbl_active.rowCount()
                self.tbl_active.insertRow(r)

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

            fills = self._keep_last_3_days(self._fills_cache)
            self.tbl_history.setRowCount(0)
            for rec in fills:
                if rec.get("account_id") != self._account_id:
                    continue
                if selected_figi and rec.get("figi") != selected_figi:
                    continue

                r = self.tbl_history.rowCount()
                self.tbl_history.insertRow(r)
                self.tbl_history.setItem(r, 0, QtWidgets.QTableWidgetItem(str(rec.get("time", ""))))
                self.tbl_history.setItem(r, 1, QtWidgets.QTableWidgetItem(str(rec.get("ticker", ""))))
                self.tbl_history.setItem(r, 2, QtWidgets.QTableWidgetItem(str(rec.get("side", ""))))
                self.tbl_history.setItem(r, 3, QtWidgets.QTableWidgetItem(str(rec.get("order_type", ""))))
                self.tbl_history.setItem(r, 4, QtWidgets.QTableWidgetItem(str(rec.get("lots", ""))))
                self.tbl_history.setItem(r, 5, QtWidgets.QTableWidgetItem(str(rec.get("price", ""))))
                self.tbl_history.setItem(r, 6, QtWidgets.QTableWidgetItem(str(rec.get("status", "Исполнена"))))
                self.tbl_history.setItem(r, 7, QtWidgets.QTableWidgetItem(str(rec.get("order_id", ""))))
                self.tbl_history.setItem(r, 8, QtWidgets.QTableWidgetItem(str(rec.get("source", "cache"))))
        finally:
            self._is_rendering_tables = False

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

    def _remove_local_order(self, local_id: str):
        self._orders_cache = [x for x in self._orders_cache if str(x.get("local_id", "")) != local_id]
        self._save_orders_cache()
        self._render_tables()

    def _on_active_cell_clicked(self, row: int, column: int):
        if column != 8:
            return
        item = self.tbl_active.item(row, 8)
        if item is None:
            return
        local_id = str(item.data(QtCore.Qt.ItemDataRole.UserRole) or "")
        if local_id:
            self._delete_order(local_id)