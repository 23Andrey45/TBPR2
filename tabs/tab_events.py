from __future__ import annotations

import json
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from app.config import DATA_DIR, FAVORITES_FILE, TOKEN
from core.favorites_repo import load_favorites
from tabs.orders_events_stream_worker import OrdersEventsStreamWorker
from tabs.quotes_events_stream_worker import QuotesEventsStreamWorker


class EventsTab(QtWidgets.QWidget):
    SUBSCRIPTIONS_LOG_FILE = DATA_DIR / "stream_subscriptions_log.jsonl"

    def __init__(self, trading_context, instruments_controller=None, parent=None):
        super().__init__(parent)
        self.trading_context = trading_context
        self.instruments_controller = instruments_controller

        self._thread: QtCore.QThread | None = None
        self._worker: OrdersEventsStreamWorker | None = None
        self._quotes_thread: QtCore.QThread | None = None
        self._quotes_worker: QuotesEventsStreamWorker | None = None
        self._name_by_figi: dict[str, str] = {}

        self.lbl_status = QtWidgets.QLabel("Готово к запуску stream")

        self.ed_account = QtWidgets.QLineEdit(str(getattr(self.trading_context, "account_id", "") or ""))
        self.ed_account.setPlaceholderText("account_id")

        self.btn_start = QtWidgets.QPushButton("Старт stream")
        self.btn_stop = QtWidgets.QPushButton("Стоп")
        self.btn_clear = QtWidgets.QPushButton("Очистить")
        self.btn_stop.setEnabled(False)

        self.tbl = QtWidgets.QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(["received_at", "event_type", "order_id", "status", "payload"])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        self.tbl_quotes = QtWidgets.QTableWidget(0, 7)
        self.tbl_quotes.setHorizontalHeaderLabels(
            ["received_at", "event_type", "figi", "instrument", "price", "time", "payload"]
        )
        self.tbl_quotes.horizontalHeader().setStretchLastSection(True)
        self.tbl_quotes.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        self.lbl_sub_info = QtWidgets.QLabel("Подписка: -")
        self.lbl_sub_info.setWordWrap(True)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Account:"))
        top.addWidget(self.ed_account, 1)
        top.addWidget(self.btn_start)
        top.addWidget(self.btn_stop)
        top.addWidget(self.btn_clear)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.lbl_sub_info)
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        split.addWidget(self.tbl)
        split.addWidget(self.tbl_quotes)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        layout.addWidget(self.lbl_status)

        self.btn_start.clicked.connect(self.start_stream)
        self.btn_stop.clicked.connect(self.stop_stream)
        self.btn_clear.clicked.connect(self.clear_events)

        if hasattr(self.trading_context, "account_changed"):
            self.trading_context.account_changed.connect(self._on_account_changed)

    def _on_account_changed(self, account_id: str) -> None:
        if not self.ed_account.text().strip():
            self.ed_account.setText(str(account_id or ""))

    def start_stream(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return

        account_id = self.ed_account.text().strip()
        if not account_id:
            self.lbl_status.setText("Укажи account_id")
            return

        self._thread = QtCore.QThread(self)
        self._worker = OrdersEventsStreamWorker(TOKEN, account_id)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.event_received.connect(self._on_event)
        self._worker.status_changed.connect(self._on_status)
        self._worker.subscription_info.connect(self._on_subscription_info)
        self._worker.stream_closed.connect(self._on_stream_closed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._cleanup_worker)

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lbl_status.setText("Stream запущен")
        self._thread.start()

        figis = self._collect_figis_for_quotes()
        if figis:
            self._quotes_thread = QtCore.QThread(self)
            self._quotes_worker = QuotesEventsStreamWorker(TOKEN, figis)
            self._quotes_worker.moveToThread(self._quotes_thread)

            self._quotes_thread.started.connect(self._quotes_worker.run)
            self._quotes_worker.quote_received.connect(self._on_quote_event)
            self._quotes_worker.status_changed.connect(self._on_quotes_status)
            self._quotes_worker.subscription_info.connect(self._on_quotes_subscription_info)
            self._quotes_worker.stream_closed.connect(self._on_quotes_stream_closed)
            self._quotes_worker.finished.connect(self._quotes_thread.quit)
            self._quotes_worker.finished.connect(self._quotes_worker.deleteLater)
            self._quotes_thread.finished.connect(self._quotes_thread.deleteLater)
            self._quotes_thread.finished.connect(self._cleanup_quotes_worker)
            self._quotes_thread.start()
        else:
            self._on_quotes_status("Quotes stream пропущен: нет FIGI в избранном")

    def stop_stream(self, wait_ms: int = 0) -> None:
        if self._worker is not None:
            self._worker.stop()
        if self._quotes_worker is not None:
            self._quotes_worker.stop()
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Остановка stream...")
        if wait_ms > 0 and self._thread is not None and self._thread.isRunning():
            self._thread.wait(wait_ms)
        if wait_ms > 0 and self._quotes_thread is not None and self._quotes_thread.isRunning():
            self._quotes_thread.wait(wait_ms)

    def clear_events(self) -> None:
        self.tbl.setRowCount(0)
        self.tbl_quotes.setRowCount(0)

    @QtCore.pyqtSlot(object)
    def _on_event(self, payload: dict) -> None:
        row = self.tbl.rowCount()
        self.tbl.insertRow(row)
        self.tbl.setItem(row, 0, QtWidgets.QTableWidgetItem(str(payload.get("received_at", ""))))
        self.tbl.setItem(row, 1, QtWidgets.QTableWidgetItem(str(payload.get("event_type", ""))))
        self.tbl.setItem(row, 2, QtWidgets.QTableWidgetItem(str(payload.get("order_id", ""))))
        self.tbl.setItem(row, 3, QtWidgets.QTableWidgetItem(str(payload.get("status", ""))))
        self.tbl.setItem(row, 4, QtWidgets.QTableWidgetItem(str(payload.get("payload", ""))))
        self.tbl.scrollToBottom()

        # Keep table size bounded in long-running test sessions.
        if self.tbl.rowCount() > 500:
            self.tbl.removeRow(0)

    @QtCore.pyqtSlot(str)
    def _on_status(self, text: str) -> None:
        self.lbl_status.setText(text)

    @QtCore.pyqtSlot(str)
    def _on_quotes_status(self, text: str) -> None:
        self.lbl_status.setText(text)

    @QtCore.pyqtSlot(object)
    def _on_subscription_info(self, payload: dict) -> None:
        text = (
            f"Подписка: target={payload.get('target', '')}, "
            f"service={payload.get('service', '')}, "
            f"method={payload.get('method', '')}, "
            f"attempt={payload.get('attempt', '')}, "
            f"account_id={payload.get('account_id', '')}"
        )
        self.lbl_sub_info.setText(text)
        self._append_subscription_log({"type": "subscribe", **payload})

    @QtCore.pyqtSlot(object)
    def _on_stream_closed(self, payload: dict) -> None:
        text = (
            f"Подписка закрыта: reason={payload.get('reason', '')}, "
            f"close_method={payload.get('close_method', '')}, "
            f"target={payload.get('target', '')}, method={payload.get('method', '')}"
        )
        self.lbl_sub_info.setText(text)
        self._append_subscription_log({"type": "closed", **payload})

    @QtCore.pyqtSlot(object)
    def _on_quotes_subscription_info(self, payload: dict) -> None:
        text = (
            f"Quotes подписка: target={payload.get('target', '')}, "
            f"method={payload.get('method', '')}, figis={payload.get('figis_count', '')}"
        )
        self.lbl_sub_info.setText(text)
        self._append_subscription_log({"type": "quotes_subscribe", **payload})

    @QtCore.pyqtSlot(object)
    def _on_quotes_stream_closed(self, payload: dict) -> None:
        text = (
            f"Quotes подписка закрыта: reason={payload.get('reason', '')}, "
            f"target={payload.get('target', '')}"
        )
        self.lbl_sub_info.setText(text)
        self._append_subscription_log({"type": "quotes_closed", **payload})

    @QtCore.pyqtSlot(object)
    def _on_quote_event(self, payload: dict) -> None:
        row = self.tbl_quotes.rowCount()
        self.tbl_quotes.insertRow(row)
        figi = str(payload.get("figi", ""))
        instrument_name = self._name_by_figi.get(figi, "")
        self.tbl_quotes.setItem(row, 0, QtWidgets.QTableWidgetItem(str(payload.get("received_at", ""))))
        self.tbl_quotes.setItem(row, 1, QtWidgets.QTableWidgetItem(str(payload.get("event_type", ""))))
        self.tbl_quotes.setItem(row, 2, QtWidgets.QTableWidgetItem(figi))
        self.tbl_quotes.setItem(row, 3, QtWidgets.QTableWidgetItem(instrument_name))
        self.tbl_quotes.setItem(row, 4, QtWidgets.QTableWidgetItem(str(payload.get("price", ""))))
        self.tbl_quotes.setItem(row, 5, QtWidgets.QTableWidgetItem(str(payload.get("time", ""))))
        self.tbl_quotes.setItem(row, 6, QtWidgets.QTableWidgetItem(str(payload.get("payload", ""))))
        self.tbl_quotes.scrollToBottom()

        if self.tbl_quotes.rowCount() > 500:
            self.tbl_quotes.removeRow(0)

    def _cleanup_worker(self) -> None:
        self._worker = None
        self._thread = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Stream остановлен")

    def _cleanup_quotes_worker(self) -> None:
        self._quotes_worker = None
        self._quotes_thread = None

    def _collect_figis_for_quotes(self) -> list[str]:
        figis: list[str] = []
        self._name_by_figi = {}

        if self.instruments_controller is not None:
            try:
                for info in self.instruments_controller.favorites():
                    figi = str(getattr(info, "figi", "") or getattr(info, "instrument_id", "") or "").strip()
                    if figi:
                        figis.append(figi)
                        self._name_by_figi[figi] = str(getattr(info, "name", "") or getattr(info, "ticker", "") or "")
            except Exception:
                pass

        if not figis:
            try:
                favorites = load_favorites(FAVORITES_FILE)
                for info in favorites.values():
                    figi = str(getattr(info, "figi", "") or getattr(info, "instrument_id", "") or "").strip()
                    if figi:
                        figis.append(figi)
                        if figi not in self._name_by_figi:
                            self._name_by_figi[figi] = str(getattr(info, "name", "") or getattr(info, "ticker", "") or "")
            except Exception:
                pass

        # Keep unique order.
        out: list[str] = []
        seen = set()
        for figi in figis:
            if figi in seen:
                continue
            seen.add(figi)
            out.append(figi)
        return out

    def _append_subscription_log(self, payload: dict) -> None:
        path: Path = self.SUBSCRIPTIONS_LOG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
