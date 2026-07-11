# tabs/tab_robots.py
from __future__ import annotations

from datetime import datetime, timezone
import copy
import uuid

from PyQt6 import QtCore, QtWidgets

from app.config import TOKEN
from core.instruments_catalog import InstrumentInfo, fetch_min_price_increment
from core.robots.grid_simple import build_fixed_grid_levels, build_grid_view_rows
from core.robots.repository import load_robots, save_robots
from tabs.robots_logic import _RobotsSyncWorker, _fmt_price, _price_key
from tabs.instruments_controller import InstrumentsController
from tabs.quotes_hub import QuotesHub
from tabs.tab_sandbox_trading import FavoritesOnlyPicker
from tabs.trading_context import TradingContext


class RobotsTab(QtWidgets.QWidget):
    def __init__(
        self,
        instruments_controller: InstrumentsController,
        quotes_hub: QuotesHub,
        trading_context: TradingContext,
        positions_hub=None,
        parent=None,
    ):
        super().__init__(parent)

        self.instr_controller = instruments_controller
        self.quotes_hub = quotes_hub
        self.trading_context = trading_context
        self._selected_instrument: InstrumentInfo | None = None
        self._current_robot_id: str | None = None
        self._robots: list[dict] = load_robots()
        self._account_id = self.trading_context.account_id
        self._sync_thread: QtCore.QThread | None = None
        self._sync_worker = None
        self.positions_hub = positions_hub

        # Справа тот же переиспользуемый виджет избранного, что и на вкладке Торговля.
        self.favorites_panel = FavoritesOnlyPicker(
            controller=self.instr_controller,
            quotes_hub=self.quotes_hub,
            positions_hub=self.positions_hub,
            trading_context=self.trading_context,
            parent=self,
        )
        self.favorites_panel.instrument_selected.connect(self._on_instrument_selected)
        self.quotes_hub.quotes_updated.connect(self._on_quotes_updated)
        self.trading_context.account_changed.connect(self._on_account_changed)

        # Управление роботом
        self.ed_start_price = QtWidgets.QLineEdit()
        self.ed_step_pct = QtWidgets.QLineEdit("1")
        self.ed_steps_down = QtWidgets.QLineEdit("5")
        self.ed_steps_up = QtWidgets.QLineEdit("5")

        self.btn_build = QtWidgets.QPushButton("Сформировать")
        self.btn_start = QtWidgets.QPushButton("Запустить")
        self.btn_stop = QtWidgets.QPushButton("Остановить")

        self.lbl_status = QtWidgets.QLabel("")

        self.tbl_robots = QtWidgets.QTableWidget(0, 8)
        self.tbl_robots.setHorizontalHeaderLabels(
            ["ID", "Тип", "Инструмент", "Тек.цена", "Статус", "Создан", "b | s", "Удалить"]
        )
        self.tbl_robots.horizontalHeader().setStretchLastSection(True)
        self.tbl_robots.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_robots.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)

        self.tbl_grid = QtWidgets.QTableWidget(0, 4)
        self.tbl_grid.setHorizontalHeaderLabels(["Маркер", "Цена", "Заявки", "Сделок b|s"])
        self.tbl_grid.horizontalHeader().setStretchLastSection(True)
        self.tbl_grid.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        form = QtWidgets.QFormLayout()
        form.addRow("Стартовая цена:", self.ed_start_price)
        form.addRow("Размер шага, %:", self.ed_step_pct)
        form.addRow("Шагов вниз:", self.ed_steps_down)
        form.addRow("Шагов вверх:", self.ed_steps_up)

        actions = QtWidgets.QHBoxLayout()
        actions.addWidget(self.btn_build)
        actions.addWidget(self.btn_start)
        actions.addWidget(self.btn_stop)
        actions.addStretch()

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.addLayout(form)
        right_layout.addLayout(actions)
        right_layout.addWidget(self.lbl_status)
        right_layout.addWidget(self.tbl_robots, 2)
        right_layout.addWidget(self.tbl_grid, 3)

        self.btn_build.clicked.connect(self._build_robot)
        self.btn_start.clicked.connect(lambda: self._set_selected_robot_status("Запущен"))
        self.btn_stop.clicked.connect(lambda: self._set_selected_robot_status("Остановлен"))
        self.tbl_robots.itemSelectionChanged.connect(self._on_robot_selected)
        self.tbl_robots.cellClicked.connect(self._on_robot_table_clicked)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._schedule_sync)
        self._timer.start()

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(self.favorites_panel)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(splitter)

        self._render_robots_table()
        self._schedule_sync()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _on_instrument_selected(self, info: InstrumentInfo):
        self._selected_instrument = info
        price = self.quotes_hub.get_price_text(info) or self.favorites_panel.get_price_for(info)
        if price and price != "-":
            self.ed_start_price.setText(price)

    def _on_account_changed(self, account_id: str):
        self._account_id = account_id

    def _on_quotes_updated(self, _payload: dict):
        selected_robot_id = self._selected_robot_id()
        for rec in self._robots:
            key = str(rec.get("fav_key", "") or "")
            if not key:
                continue

            info = InstrumentInfo(
                kind=str(rec.get("instrument_kind", "") or ""),
                instrument_id=str(rec.get("instrument_figi", "") or ""),
                ticker=str(rec.get("instrument_ticker", "") or ""),
                name=str(rec.get("instrument_name", "") or ""),
                isin=str(rec.get("instrument_isin", "") or ""),
                figi=str(rec.get("instrument_figi", "") or ""),
                uid="",
            )

            p = self.quotes_hub.get_price(info)
            if p is None:
                continue
            if float(rec.get("current_price", 0.0) or 0.0) != float(p):
                rec["current_price"] = float(p)
                self._update_robot_row_price(str(rec.get("robot_id", "")), float(p))

        if selected_robot_id:
            # Даже если значение не изменилось в кеше, обновляем открытую сетку
            # от последней живой цены из QuotesHub.
            rec = self._find_robot(selected_robot_id)
            if rec is not None:
                self._render_grid_for(rec)

    def _build_robot(self):
        if self._selected_instrument is None:
            self.lbl_status.setText("Выбери инструмент в таблице Избранное")
            return

        try:
            start_price = float(self.ed_start_price.text().strip().replace(",", "."))
            step_pct = float(self.ed_step_pct.text().strip().replace(",", "."))
            steps_down = int(self.ed_steps_down.text().strip())
            steps_up = int(self.ed_steps_up.text().strip())
            if start_price <= 0 or step_pct <= 0 or steps_down < 0 or steps_up < 0:
                raise ValueError
        except Exception:
            self.lbl_status.setText("Проверь параметры робота")
            return

        current_price = start_price
        price_text = self.quotes_hub.get_price_text(self._selected_instrument) or self.favorites_panel.get_price_for(
            self._selected_instrument
        )
        try:
            if price_text and price_text != "-":
                current_price = float(price_text.replace(",", "."))
        except Exception:
            pass

        rec = {
            "robot_id": str(uuid.uuid4())[:8],
            "robot_type": "grid_simple",
            "instrument_kind": self._selected_instrument.kind,
            "instrument_ticker": self._selected_instrument.ticker,
            "instrument_name": self._selected_instrument.name,
            "instrument_isin": self._selected_instrument.isin,
            "instrument_figi": self._selected_instrument.figi,
            "fav_key": self._selected_instrument.fav_key(),
            "start_price": start_price,
            "step_pct": step_pct,
            "steps_down": steps_down,
            "steps_up": steps_up,
            "last_trade_price": start_price,
            "current_price": current_price,
            "status": "Остановлен",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tick_size": 0.0,
            "grid_levels": [],
            "active_orders": [],
            "deals_by_level": {},
        }

        tick = fetch_min_price_increment(
            token=TOKEN,
            figi=self._selected_instrument.figi,
            instrument_id=self._selected_instrument.instrument_id,
        )
        if tick is None or tick <= 0:
            tick = 0.0
        rec["tick_size"] = float(tick)

        levels = build_fixed_grid_levels(
            start_price=float(start_price),
            step_pct=float(step_pct),
            steps_down=int(steps_down),
            steps_up=int(steps_up),
            tick_size=float(tick),
        )
        rec["grid_levels"] = levels

        self._robots.append(rec)
        save_robots(self._robots)
        self._render_robots_table(select_robot_id=rec["robot_id"])
        self._render_grid_for(rec)
        self.lbl_status.setText(
            f"Робот сформирован (шаг цены: {float(tick):g}, старт: {start_price:g})"
        )

    def _render_robots_table(self, select_robot_id: str | None = None):
        target_id = select_robot_id or self._current_robot_id
        self.tbl_robots.setRowCount(0)
        for rec in self._robots:
            r = self.tbl_robots.rowCount()
            self.tbl_robots.insertRow(r)

            self.tbl_robots.setItem(r, 0, QtWidgets.QTableWidgetItem(str(rec.get("robot_id", ""))))
            self.tbl_robots.setItem(r, 1, QtWidgets.QTableWidgetItem(str(rec.get("robot_type", ""))))
            self.tbl_robots.setItem(r, 2, QtWidgets.QTableWidgetItem(str(rec.get("instrument_ticker", ""))))
            self.tbl_robots.setItem(r, 3, QtWidgets.QTableWidgetItem(str(rec.get("current_price", ""))))
            self.tbl_robots.setItem(r, 4, QtWidgets.QTableWidgetItem(str(rec.get("status", ""))))
            self.tbl_robots.setItem(r, 5, QtWidgets.QTableWidgetItem(str(rec.get("created_at", ""))))
            self.tbl_robots.setItem(r, 6, QtWidgets.QTableWidgetItem(self._total_deals_text(rec)))
            rid = str(rec.get("robot_id", ""))
            del_item = QtWidgets.QTableWidgetItem("Удалить")
            del_item.setData(QtCore.Qt.ItemDataRole.UserRole, rid)
            self.tbl_robots.setItem(r, 7, del_item)

            if target_id and rid == target_id:
                self.tbl_robots.selectRow(r)

    def _delete_robot(self, robot_id: str):
        self._robots = [x for x in self._robots if str(x.get("robot_id", "")) != robot_id]
        if self._current_robot_id == robot_id:
            self._current_robot_id = None
        save_robots(self._robots)
        self._render_robots_table()
        self.tbl_grid.setRowCount(0)
        self.lbl_status.setText("Робот удален")

    def _on_robot_table_clicked(self, row: int, column: int):
        if column != 7:
            return
        item = self.tbl_robots.item(row, 7)
        if item is None:
            return
        rid = str(item.data(QtCore.Qt.ItemDataRole.UserRole) or "")
        if rid:
            self._delete_robot(rid)

    def _total_deals_text(self, rec: dict) -> str:
        deals_by_level = rec.get("deals_by_level", {}) or {}
        total_b = 0
        total_s = 0
        for row in deals_by_level.values():
            if not isinstance(row, dict):
                continue
            total_b += int(row.get("b", 0) or 0)
            total_s += int(row.get("s", 0) or 0)
        return f"{total_b} | {total_s}"

    def _update_robot_row_price(self, robot_id: str, price: float):
        if not robot_id:
            return
        for row in range(self.tbl_robots.rowCount()):
            id_item = self.tbl_robots.item(row, 0)
            if id_item is None:
                continue
            if str(id_item.text()) != robot_id:
                continue
            price_item = self.tbl_robots.item(row, 3)
            if price_item is None:
                price_item = QtWidgets.QTableWidgetItem()
                self.tbl_robots.setItem(row, 3, price_item)
            price_item.setText(f"{price:.6f}".rstrip("0").rstrip("."))
            return

    def _schedule_sync(self):
        if not self.isVisible():
            return
        if not self._account_id:
            return
        if self._sync_thread and self._sync_thread.isRunning():
            return

        robots = copy.deepcopy(self._robots)
        self._sync_thread = QtCore.QThread(self)
        self._sync_worker = _RobotsSyncWorker(TOKEN, self._account_id, robots)
        self._sync_worker.moveToThread(self._sync_thread)

        self._sync_thread.started.connect(self._sync_worker.run)
        self._sync_worker.loaded.connect(self._on_sync_loaded)
        self._sync_worker.finished.connect(self._sync_thread.quit)
        self._sync_worker.finished.connect(self._sync_worker.deleteLater)
        self._sync_thread.finished.connect(self._sync_thread.deleteLater)
        self._sync_thread.finished.connect(self._on_sync_finished)

        self._sync_thread.start()

    def _on_sync_loaded(self, robots: list[dict]):
        selected_robot_id = self._selected_robot_id()
        self._robots = robots or []
        save_robots(self._robots)
        self._render_robots_table(select_robot_id=selected_robot_id)
        if selected_robot_id:
            rec = self._find_robot(selected_robot_id)
            if rec is not None:
                self._render_grid_for(rec)

    def _on_sync_finished(self):
        self._sync_worker = None
        self._sync_thread = None

    def _on_robot_selected(self):
        sel = self.tbl_robots.selectionModel().selectedRows()
        if not sel:
            return
        rid = self.tbl_robots.item(sel[0].row(), 0)
        if rid is None:
            return
        self._current_robot_id = str(rid.text())
        rec = self._find_robot(str(rid.text()))
        if rec is not None:
            self._render_grid_for(rec)

    def _find_robot(self, robot_id: str) -> dict | None:
        for rec in self._robots:
            if str(rec.get("robot_id", "")) == robot_id:
                return rec
        return None

    def _selected_robot_id(self) -> str | None:
        sel = self.tbl_robots.selectionModel().selectedRows()
        if sel:
            rid_item = self.tbl_robots.item(sel[0].row(), 0)
            if rid_item is not None:
                rid = str(rid_item.text() or "").strip()
                if rid:
                    self._current_robot_id = rid
                    return rid
        return self._current_robot_id

    def _set_selected_robot_status(self, status: str):
        sel = self.tbl_robots.selectionModel().selectedRows()
        if not sel:
            self.lbl_status.setText("Выбери робота в таблице")
            return
        rid_item = self.tbl_robots.item(sel[0].row(), 0)
        if rid_item is None:
            return
        rec = self._find_robot(str(rid_item.text()))
        if rec is None:
            return
        rec["status"] = status
        save_robots(self._robots)
        self._render_robots_table(select_robot_id=str(rec.get("robot_id", "")))
        self.lbl_status.setText(f"Робот: {status}")
        self._schedule_sync()

    def _render_grid_for(self, rec: dict):
        # Берем актуальную цену из общего потока котировок в момент перерисовки сетки.
        info = InstrumentInfo(
            kind=str(rec.get("instrument_kind", "") or ""),
            instrument_id=str(rec.get("instrument_figi", "") or ""),
            ticker=str(rec.get("instrument_ticker", "") or ""),
            name=str(rec.get("instrument_name", "") or ""),
            isin=str(rec.get("instrument_isin", "") or ""),
            figi=str(rec.get("instrument_figi", "") or ""),
            uid="",
        )
        live_price = self.quotes_hub.get_price(info)
        if live_price is not None:
            rec["current_price"] = float(live_price)

        rows = build_grid_view_rows(
            levels=[float(x) for x in (rec.get("grid_levels", []) or [])],
            last_trade_price=float(rec.get("last_trade_price", 0.0) or 0.0),
            current_price=float(rec.get("current_price", 0.0) or 0.0),
        )
        tick = float(rec.get("tick_size", 0.0) or 0.0)

        self.tbl_grid.setRowCount(0)
        for row in rows:
            r = self.tbl_grid.rowCount()
            self.tbl_grid.insertRow(r)
            marker_text_raw = str(row.get("marker", "") or "")
            marker_text = marker_text_raw
            if marker_text_raw:
                try:
                    marker_text = _fmt_price(float(marker_text_raw), tick)
                except Exception:
                    marker_text = marker_text_raw
            marker_item = QtWidgets.QTableWidgetItem(marker_text)
            price = float(row.get("price", 0.0) or 0.0)
            price_item = QtWidgets.QTableWidgetItem(_fmt_price(price, tick))

            level_key = _price_key(price)
            deals = rec.get("deals_by_level", {}).get(level_key, {"b": 0, "s": 0})
            deals_text = f"{int(deals.get('b', 0) or 0)} | {int(deals.get('s', 0) or 0)}"

            tokens: list[str] = []
            for ao in rec.get("active_orders", []) or []:
                if _price_key(float(ao.get("level_price", 0.0) or 0.0)) != level_key:
                    continue
                side = str(ao.get("side", "")).upper()
                oid = str(ao.get("order_id", "") or "")
                short = oid[:6] if oid else ""
                if side == "BUY":
                    tokens.append(f"B#{short}")
                elif side == "SELL":
                    tokens.append(f"S#{short}")

            orders_item = QtWidgets.QTableWidgetItem(" ".join(tokens))
            deals_item = QtWidgets.QTableWidgetItem(deals_text)

            color = row.get("marker_color")
            if color == "up":
                marker_item.setBackground(QtCore.Qt.GlobalColor.green)
            elif color == "down":
                marker_item.setBackground(QtCore.Qt.GlobalColor.red)

            self.tbl_grid.setItem(r, 0, marker_item)
            self.tbl_grid.setItem(r, 1, price_item)
            self.tbl_grid.setItem(r, 2, orders_item)
            self.tbl_grid.setItem(r, 3, deals_item)