# tabs/tab_robots.py
from __future__ import annotations

from datetime import datetime, timezone
import copy
import uuid

from PyQt6 import QtCore, QtWidgets

from app.config import TOKEN
from app.app_context import AppContext
from core.instruments_catalog import InstrumentInfo, fetch_min_price_increment
from robots.grid_simple import build_fixed_grid_levels, build_grid_view_rows
from robots.repository import load_robots, save_robots
from robots.robots_logic import _RobotsSyncWorker, _fmt_price, _price_key
from instruments.instruments_controller import InstrumentsController
from market_data.quotes_hub import QuotesHub
from sandbox_trading.tab_sandbox_trading import FavoritesOnlyPicker


class RobotsTab(QtWidgets.QWidget):
    def __init__(
        self,
        instruments_controller: InstrumentsController,
        quotes_hub: QuotesHub,
        app_context: AppContext,
        positions_hub=None,
        parent=None,
    ):
        super().__init__(parent)

        self.instr_controller = instruments_controller
        self.quotes_hub = quotes_hub
        self.app_context = app_context
        self._selected_instrument: InstrumentInfo | None = None
        self._current_robot_id: str | None = None
        self._robots: list[dict] = load_robots()
        self._account_id = self.app_context.sandbox_account_id
        self._sync_thread: QtCore.QThread | None = None
        self._sync_worker = None
        self.positions_hub = positions_hub

        # Справа тот же переиспользуемый виджет избранного, что и на вкладке Торговля.
        self.favorites_panel = FavoritesOnlyPicker(
            controller=self.instr_controller,
            quotes_hub=self.quotes_hub,
            positions_hub=self.positions_hub,
            app_context=self.app_context,
            parent=self,
        )
        self.favorites_panel.instrument_selected.connect(self._on_instrument_selected)
        self.quotes_hub.quotes_updated.connect(self._on_quotes_updated)
        self.app_context.account_changed.connect(self._on_account_changed)

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
        price_text = self.quotes_hub.get_price_text(self._selected_instrument) or self.favorites_panel.get_price_for(self._selected_instrument)
        if price_text and price_text != "-":
            current_price = float(price_text)

        tick = fetch_min_price_increment(TOKEN, figi=self._selected_instrument.figi) or 0.0
        levels = build_fixed_grid_levels(
            start_price=start_price,
            step_pct=step_pct,
            steps_down=steps_down,
            steps_up=steps_up,
            tick_size=tick,
        )
        rows = build_grid_view_rows(levels=levels, last_trade_price=start_price, current_price=current_price)

        robot_id = str(uuid.uuid4())
        rec = {
            "robot_id": robot_id,
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
            "grid_levels": levels,
            "last_trade_price": start_price,
            "current_price": current_price,
            "status": "Новый",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "active_orders": [],
            "deals_by_level": {},
        }
        self._robots.append(rec)
        save_robots(self._robots)
        self._render_robots_table()
        self._current_robot_id = robot_id
        self._render_grid_for(rec)
        self.lbl_status.setText(f"Робот {robot_id[:8]}... сформирован")

    def _set_selected_robot_status(self, status: str):
        robot_id = self._selected_robot_id()
        if not robot_id:
            self.lbl_status.setText("Выбери робота")
            return
        rec = self._find_robot(robot_id)
        if rec is None:
            return
        rec["status"] = status
        save_robots(self._robots)
        self._render_robots_table()
        self.lbl_status.setText(f"Статус: {status}")

    def _selected_robot_id(self) -> str | None:
        sel = self.tbl_robots.selectionModel().selectedRows()
        if not sel:
            return None
        r = sel[0].row()
        item = self.tbl_robots.item(r, 0)
        if item is None:
            return None
        return str(item.text())

    def _find_robot(self, robot_id: str) -> dict | None:
        for rec in self._robots:
            if str(rec.get("robot_id", "")) == robot_id:
                return rec
        return None

    def _on_robot_selected(self):
        robot_id = self._selected_robot_id()
        if not robot_id:
            return
        rec = self._find_robot(robot_id)
        if rec is None:
            return
        self._current_robot_id = robot_id
        self._render_grid_for(rec)

    def _on_robot_table_clicked(self, row: int, column: int):
        if column != 7:
            return
        item = self.tbl_robots.item(row, 0)
        if item is None:
            return
        robot_id = str(item.text())
        self._robots = [r for r in self._robots if str(r.get("robot_id", "")) != robot_id]
        save_robots(self._robots)
        self._render_robots_table()
        self.lbl_status.setText(f"Робот {robot_id[:8]}... удалён")

    def _render_robots_table(self):
        self.tbl_robots.setRowCount(0)
        self.tbl_robots.setSortingEnabled(False)
        for rec in self._robots:
            r = self.tbl_robots.rowCount()
            self.tbl_robots.insertRow(r)
            self.tbl_robots.setItem(r, 0, QtWidgets.QTableWidgetItem(str(rec.get("robot_id", "")[:8])))
            self.tbl_robots.setItem(r, 1, QtWidgets.QTableWidgetItem(str(rec.get("robot_type", ""))))
            ticker = str(rec.get("instrument_ticker", ""))
            self.tbl_robots.setItem(r, 2, QtWidgets.QTableWidgetItem(ticker))
            price = float(rec.get("current_price", 0.0) or 0.0)
            self.tbl_robots.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{price:.6f}" if price else "-"))
            self.tbl_robots.setItem(r, 4, QtWidgets.QTableWidgetItem(str(rec.get("status", ""))))
            created = str(rec.get("created_at", ""))
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    created = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass
            self.tbl_robots.setItem(r, 5, QtWidgets.QTableWidgetItem(created))
            deals = rec.get("deals_by_level", {}) or {}
            total_b = sum(x.get("b", 0) for x in deals.values())
            total_s = sum(x.get("s", 0) for x in deals.values())
            self.tbl_robots.setItem(r, 6, QtWidgets.QTableWidgetItem(f"{total_b} | {total_s}"))
            del_item = QtWidgets.QTableWidgetItem("❌")
            del_item.setFlags(del_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.tbl_robots.setItem(r, 7, del_item)
        self.tbl_robots.setSortingEnabled(True)

    def _update_robot_row_price(self, robot_id: str, price: float):
        for r in range(self.tbl_robots.rowCount()):
            item = self.tbl_robots.item(r, 0)
            if item and str(item.text()) == robot_id[:8]:
                self.tbl_robots.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{price:.6f}"))
                break

    def _render_grid_for(self, rec: dict):
        rows = build_grid_view_rows(
            levels=rec.get("grid_levels", []),
            last_trade_price=float(rec.get("last_trade_price", 0.0) or 0.0),
            current_price=float(rec.get("current_price", 0.0) or 0.0),
        )
        deals_by_level = rec.get("deals_by_level", {}) or {}
        active_orders = rec.get("active_orders", []) or []

        self.tbl_grid.setRowCount(0)
        for row in rows:
            r = self.tbl_grid.rowCount()
            self.tbl_grid.insertRow(r)
            marker = str(row.get("marker", "") or "")
            self.tbl_grid.setItem(r, 0, QtWidgets.QTableWidgetItem(marker))
            price = float(row.get("price", 0.0))
            tick = fetch_min_price_increment(TOKEN, figi=rec.get("instrument_figi", "")) or 0.0
            self.tbl_grid.setItem(r, 1, QtWidgets.QTableWidgetItem(_fmt_price(price, tick)))
            orders_at_level = [ao for ao in active_orders if _price_key(float(ao.get("level_price", 0.0))) == _price_key(price)]
            self.tbl_grid.setItem(r, 2, QtWidgets.QTableWidgetItem(str(len(orders_at_level))))
            key = _price_key(price)
            d = deals_by_level.get(key, {"b": 0, "s": 0})
            self.tbl_grid.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{d.get('b', 0)} | {d.get('s', 0)}"))

    def _schedule_sync(self):
        if self._sync_thread is not None and self._sync_thread.isRunning():
            return
        if not self._account_id:
            return
        self._sync_thread = QtCore.QThread(self)
        self._sync_worker = _RobotsSyncWorker(TOKEN, self._account_id, self._robots)
        self._sync_worker.moveToThread(self._sync_thread)
        self._sync_thread.started.connect(self._sync_worker.run)
        self._sync_worker.loaded.connect(self._on_sync_loaded)
        self._sync_worker.finished.connect(self._sync_thread.quit)
        self._sync_worker.finished.connect(self._sync_worker.deleteLater)
        self._sync_thread.finished.connect(self._sync_thread.deleteLater)
        self._sync_thread.start()

    def _on_sync_loaded(self, robots: list[dict]):
        self._robots = robots
        save_robots(self._robots)
        self._render_robots_table()
        robot_id = self._selected_robot_id()
        if robot_id:
            rec = self._find_robot(robot_id)
            if rec is not None:
                self._render_grid_for(rec)