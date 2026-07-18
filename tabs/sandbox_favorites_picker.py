from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from PyQt6 import QtCore, QtWidgets
from t_tech.invest import Client

# ✅ ЛОГИРОВАНИЕ - ВЫВОД В КОНСОЛЬ
_FAV_LOG = []


def _log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    log_line = f"[FAV-PICKER {ts}] {msg}"
    _FAV_LOG.append(log_line)
    if len(_FAV_LOG) > 100:
        _FAV_LOG.pop(0)
    print(log_line)  # ✅ ВЫВОД В КОНСОЛЬ


from app.config import TOKEN
from core.instruments_catalog import InstrumentInfo
from tabs.instruments_controller import InstrumentsController
from tabs.quotes_hub import QuotesHub
from workers import TradingStatusLoader


class _FavoritesPositionsLoader(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)  # dict[str, float], key=figi
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str):
        super().__init__()
        self.token = token
        self.account_id = account_id

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.loaded.emit(self._load_positions())
        except Exception:
            import traceback

            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()

    def _load_positions(self) -> dict[str, float]:
        out: dict[str, float] = {}

        try:
            from core.sandbox_trading_api import get_sandbox_portfolio

            rows = get_sandbox_portfolio(self.token, self.account_id)
            for row in rows:
                figi = str(getattr(row, "figi", "") or "").strip()
                qty = float(getattr(row, "quantity", 0.0) or 0.0)
                if figi:
                    out[figi] = qty
            return out
        except Exception:
            pass

        with Client(token=self.token) as client:
            sb = getattr(client, "sandbox", None)
            if sb is None:
                return out

            method = getattr(sb, "get_sandbox_portfolio", None)
            if method is None:
                return out

            try:
                resp = method(account_id=self.account_id)
            except TypeError:
                return out

            positions = list(getattr(resp, "positions", []) or [])
            for pos in positions:
                figi = str(getattr(pos, "figi", "") or "").strip()
                qty = float(getattr(pos, "quantity", 0.0) or 0.0)
                if figi:
                    out[figi] = qty

        return out


class FavoritesOnlyPicker(QtWidgets.QWidget):
    instrument_selected = QtCore.pyqtSignal(object)

    # ✅ ИСПРАВЛЕНИЕ: Флаг блокировки рекурсивных обновлений
    _updating = False

    def __init__(
            self,
            controller: InstrumentsController,
            quotes_hub: QuotesHub,
            positions_hub: Any = None,
            trading_context: Any = None,
            parent=None,
    ):
        super().__init__(parent)
        self.controller = controller
        self.quotes_hub = quotes_hub
        self.positions_hub = positions_hub
        self.trading_context = trading_context if trading_context is not None else getattr(parent, "trading_context",
                                                                                           None)

        self._selected: Optional[InstrumentInfo] = None
        self._price_by_key: dict[str, str] = {}
        self._qty_by_figi: dict[str, float] = {}
        self._account_id = str(getattr(self.trading_context, "account_id", "") or "")
        self._qty_thread: Optional[QtCore.QThread] = None
        self._qty_worker = None
        self._render_scheduled = False
        self._last_render_time: Optional[datetime] = None
        self._update_count = 0

        _log("FavoritesOnlyPicker initialized")

        self.lbl = QtWidgets.QLabel("Избранное")
        self.btn_refresh_prices = QtWidgets.QPushButton("Обновить цены")
        self.btn_refresh_qty = QtWidgets.QPushButton("Обновить количество")

        self.tbl_fav = QtWidgets.QTableWidget(0, 6)
        self.tbl_fav.setHorizontalHeaderLabels(["Type", "Инструмент", "ISIN", "Цена", "Статус", "Количество"])
        self.tbl_fav.horizontalHeader().setStretchLastSection(True)
        self.tbl_fav.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_fav.setWordWrap(True)
        self.tbl_fav.verticalHeader().setDefaultSectionSize(44)
        self.tbl_fav.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_fav.setColumnHidden(0, True)
        self.tbl_fav.setColumnHidden(2, True)
        self.tbl_fav.setColumnWidth(1, 250)
        self.tbl_fav.setColumnWidth(3, 100)
        self.tbl_fav.setColumnWidth(4, 100)  # Статус
        self.tbl_fav.setColumnWidth(5, 120)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.lbl)
        top.addStretch()
        top.addWidget(self.btn_refresh_prices)
        top.addWidget(self.btn_refresh_qty)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tbl_fav)

        self.controller.favorites_updated.connect(self._on_favorites_updated)
        self.tbl_fav.cellDoubleClicked.connect(self._emit_selected)
        self.btn_refresh_prices.clicked.connect(self.quotes_hub.request_refresh)
        self.btn_refresh_qty.clicked.connect(self.refresh_quantities)
        self.quotes_hub.quotes_updated.connect(self._on_quotes_updated)
        self.quotes_hub.trading_status_updated.connect(self._on_trading_status_updated)

        # ✅ Таймер для периодического обновления статусов в UI
        self._status_update_timer = QtCore.QTimer(self)
        self._status_update_timer.setInterval(5000)  # 5 секунд
        self._status_update_timer.timeout.connect(self._update_status_display)
        self._status_update_timer.start()

        # ✅ Воркер для загрузки статусов
        self._status_thread: Optional[QtCore.QThread] = None
        self._status_worker = None

        _log("Status update timer started")

        if self.positions_hub is not None and hasattr(self.positions_hub, "positions_updated"):
            self.positions_hub.positions_updated.connect(self._on_positions_updated)

        if self.trading_context is not None and hasattr(self.trading_context, "account_changed"):
            self.trading_context.account_changed.connect(self._on_account_changed)

        self.controller.emit_initial_state()
        QtCore.QTimer.singleShot(0, self.refresh_quantities)

    def _on_account_changed(self, account_id: str):
        self._account_id = str(account_id or "")
        self.refresh_quantities()

    def refresh_quantities(self):
        # ✅ ИСПРАВЛЕНИЕ: Защита от повторных вызовов
        if self._updating:
            return
        if self.positions_hub is not None:
            try:
                self.positions_hub.request_refresh()
            except Exception:
                pass
            return

        if self._qty_thread is not None and self._qty_thread.isRunning():
            return

        if not self._account_id:
            self._qty_by_figi = {}
            self._request_render()
            return

        self._qty_thread = QtCore.QThread(self)
        self._qty_worker = _FavoritesPositionsLoader(TOKEN, self._account_id)
        self._qty_worker.moveToThread(self._qty_thread)

        self._qty_thread.started.connect(self._qty_worker.run)
        self._qty_worker.loaded.connect(self._on_quantities_loaded)
        self._qty_worker.error.connect(self._on_quantities_error)
        self._qty_worker.finished.connect(self._qty_thread.quit)
        self._qty_worker.finished.connect(self._qty_worker.deleteLater)
        self._qty_thread.finished.connect(self._qty_thread.deleteLater)
        self._qty_thread.finished.connect(self._cleanup_qty_worker)

        self._qty_thread.start()

    def _cleanup_qty_worker(self):
        self._qty_worker = None
        self._qty_thread = None

    def _on_quantities_loaded(self, qty_by_figi: dict[str, float]):
        self._qty_by_figi = qty_by_figi or {}
        # ✅ ИСПРАВЛЕНИЕ: Используем отложенный рендер
        self._request_render()

    def _on_positions_updated(self, _payload: dict):
        if self.positions_hub is None:
            return
        by_figi: dict[str, float] = {}
        for info in self.controller.favorites():
            figi = (info.figi or info.instrument_id or "").strip()
            if not figi:
                continue
            by_figi[figi] = float(self.positions_hub.get_qty(info))
        self._qty_by_figi = by_figi
        # ✅ ИСПРАВЛЕНИЕ: Используем отложенный рендер
        self._request_render()

    def _on_trading_status_updated(self, statuses: dict):
        """Обновление статусов торгов."""
        _log(f"_on_trading_status_updated: {len(statuses)} statuses")
        # Обновляем отображение статусов
        self._update_status_display()

    def _update_status_display(self):
        """Обновить только столбец статусов в таблице."""
        if self.tbl_fav.rowCount() == 0:
            return

        _log(f"_update_status_display: {self.tbl_fav.rowCount()} rows")

        for r in range(self.tbl_fav.rowCount()):
            item = self.tbl_fav.item(r, 0)
            if item is None:
                continue

            info = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if info is None:
                continue

            figi = (info.figi or info.instrument_id or "").strip()
            if not figi:
                continue

            status = self.quotes_hub.get_trading_status(figi)
            status_text = self._get_status_text(status)

            status_item = self.tbl_fav.item(r, 4)
            if status_item:
                status_item.setText(status_text)

                # Tooltip
                if status:
                    tooltip = (
                        f"Статус: {status.get('trading_status', 'N/A')}\n"
                        f"Торги: {'✅' if status.get('api_trade_available') else '❌'}\n"
                        f"Market: {'✅' if status.get('market_order_available') else '❌'}\n"
                        f"Limit: {'✅' if status.get('limit_order_available') else '❌'}"
                    )
                    status_item.setToolTip(tooltip)

        _log("_update_status_display: DONE")

    def _on_quantities_error(self, tb: str):
        print("===== ERROR (_FavoritesOnlyPicker qty) =====")
        print(tb)
        print("============================================")

    def _qty_for(self, info: InstrumentInfo) -> float:
        figi = (info.figi or info.instrument_id or "").strip()
        if not figi:
            return 0.0
        return float(self._qty_by_figi.get(figi, 0.0) or 0.0)

    def _qty_text(self, info: InstrumentInfo) -> str:
        q = self._qty_for(info)
        if abs(q) < 1e-12:
            return "0"
        return f"{q:.6f}".rstrip("0").rstrip(".")

    def get_price_for(self, info: InstrumentInfo) -> str:
        p = self.quotes_hub.get_price_text(info)
        return p if p else "-"

    def _on_quotes_updated(self, _payload: dict):
        # ✅ ИСПРАВЛЕНИЕ: Не обновляем таблицу при каждом изменении котировок
        # Котировки обновляются каждые 3 секунды - это слишком часто
        pass

    def _request_render(self):
        # ✅ ПРОВЕРКА 1: Debounce (мин. 500 мс между рендерами)
        now = datetime.now()
        if self._last_render_time is not None:
            elapsed_ms = (now - self._last_render_time).total_seconds() * 1000
            if elapsed_ms < 500:
                return

        # ✅ ПРОВЕРКА 2: Уже запланирован
        if self._render_scheduled or self._updating:
            return

        self._render_scheduled = True
        self._update_count += 1
        _log(f"_request_render #{self._update_count}")
        QtCore.QTimer.singleShot(100, self._do_render)

    def _do_render(self):
        self._render_scheduled = False
        if self._updating:
            return

        now = datetime.now()
        if self._last_render_time is not None:
            elapsed_ms = (now - self._last_render_time).total_seconds() * 1000
            if elapsed_ms < 500:
                _log(f"_do_render SKIP: too soon ({elapsed_ms:.0f}ms)")
                return

        _log("_do_render START")
        self._last_render_time = now
        self._updating = True
        try:
            self._on_favorites_updated(self.controller.favorites())
            _log("_do_render DONE")
        except Exception as e:
            _log(f"_do_render ERROR: {e}")
        finally:
            self._updating = False

    def _on_favorites_updated(self, items: list[InstrumentInfo]):
        # ✅ ИСПРАВЛЕНИЕ: Отключаем перерисовку на время обновления
        self.tbl_fav.setUpdatesEnabled(False)
        self.tbl_fav.blockSignals(True)

        try:
            self.tbl_fav.setRowCount(0)
            for info in items:
                r = self.tbl_fav.rowCount()
                self.tbl_fav.insertRow(r)

                kind_short = kind_to_short(info.kind)
                ticker_name = f"{info.ticker} | {info.name}"
                price = self.get_price_for(info)
                qty = self._qty_text(info)

                # ✅ Получаем статус торгов
                figi = (info.figi or info.instrument_id or "").strip()
                status = self.quotes_hub.get_trading_status(figi) if figi else {}
                status_text = self._get_status_text(status)

                self.tbl_fav.setItem(r, 0, QtWidgets.QTableWidgetItem(kind_short))
                self.tbl_fav.setItem(r, 1, QtWidgets.QTableWidgetItem(ticker_name))
                self.tbl_fav.setItem(r, 2, QtWidgets.QTableWidgetItem(info.isin or ""))
                self.tbl_fav.setItem(r, 3, QtWidgets.QTableWidgetItem(price))
                self.tbl_fav.setItem(r, 4, QtWidgets.QTableWidgetItem(status_text))
                self.tbl_fav.setItem(r, 5, QtWidgets.QTableWidgetItem(qty))

                item = self.tbl_fav.item(r, 0)
                if item is not None:
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, info)

                # ✅ Tooltip с информацией о статусе
                if status:
                    tooltip = (
                        f"Статус: {status.get('trading_status', 'N/A')}\n"
                        f"Торги: {'✅' if status.get('api_trade_available') else '❌'}\n"
                        f"Market: {'✅' if status.get('market_order_available') else '❌'}\n"
                        f"Limit: {'✅' if status.get('limit_order_available') else '❌'}"
                    )
                    self.tbl_fav.item(r, 4).setToolTip(tooltip)
        finally:
            self.tbl_fav.blockSignals(False)
            self.tbl_fav.setUpdatesEnabled(True)
            self.tbl_fav.viewport().update()

        # ✅ Загружаем статусы после отрисовки
        self._request_status_load()

    def _get_status_text(self, status: dict) -> str:
        """Получить текстовое представление статуса."""
        if not status:
            return "⏳ Загрузка"

        if status.get('error'):
            return "❌ Ошибка"

        if not status.get('api_trade_available', False):
            return "🔴 Закрыто"

        if status.get('market_order_available', False):
            return "🟢 Торги"

        return "🟡 Ограничено"

    def _request_status_load(self):
        """Запросить загрузку статусов для всех FIGI."""
        if self._status_thread and self._status_thread.isRunning():
            _log("_request_status_load: SKIP - already running")
            return

        figis = []
        for info in self.controller.favorites():
            figi = (info.figi or info.instrument_id or "").strip()
            if figi:
                figis.append(figi)

        if not figis:
            _log("_request_status_load: SKIP - no figis")
            return

        _log(f"_request_status_load: {len(figis)} figis")

        self._status_thread = QtCore.QThread(self)
        self._status_worker = TradingStatusLoader(TOKEN, figis)
        self._status_worker.moveToThread(self._status_thread)

        self._status_thread.started.connect(self._status_worker.run)
        self._status_worker.loaded.connect(self._on_status_loaded)
        self._status_worker.error.connect(self._on_status_error)
        self._status_worker.finished.connect(self._status_thread.quit)
        self._status_worker.finished.connect(self._status_worker.deleteLater)
        self._status_thread.finished.connect(self._status_thread.deleteLater)
        self._status_thread.finished.connect(self._cleanup_status_worker)

        self._status_thread.start()

    def _on_status_loaded(self, statuses: dict):
        """Обработка загруженных статусов."""
        _log(f"_on_status_loaded: {len(statuses)} statuses")

        # Сохраняем в QuotesHub
        self.quotes_hub._trading_statuses = statuses

        # Обновляем таблицу
        self._update_status_display()

    def _on_status_error(self, err: str):
        """Обработка ошибки."""
        _log(f"_on_status_error: {err}")

    def _cleanup_status_worker(self):
        """Очистка воркера."""
        self._status_worker = None
        self._status_thread = None

    def _emit_selected(self, row: int, _column: int):
        item = self.tbl_fav.item(row, 0)
        if item is None:
            return
        info = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if info is not None:
            self._selected = info
            self.instrument_selected.emit(info)


def kind_to_short(kind: str) -> str:
    kind = (kind or "").lower()
    if kind == "share":
        return "SHARE"
    if kind == "bond":
        return "BOND"
    if kind == "etf":
        return "ETF"
    return kind.upper() or "?"
