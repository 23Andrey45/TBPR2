from datetime import datetime, timezone
from time import perf_counter

from PyQt6 import QtCore, QtWidgets

from app.config import TOKEN, TOKEN_ERROR, TOKEN_FILE
from tabs.instruments_controller import InstrumentsController
from tabs.positions_hub import PositionsHub
from tabs.quotes_hub import QuotesHub
from tabs.tab_home import HomeTab
from tabs.tab_events import EventsTab
from tabs.tab_journal import JournalTab
from tabs.tab_robots import RobotsTab
from tabs.tab_sandbox_trading import SandboxTradingTab
from tabs.trading_context import TradingContext

try:
    from tabs.tab_account import AccountTab
except Exception:
    AccountTab = None


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Moe prilozhenie")
        self.resize(1400, 800)

        self.home_tab = None
        self.sandbox_trading_tab = None
        self.journal_tab = None
        self.account_tab = None

        if not TOKEN:
            info = QtWidgets.QLabel(
                "Token ne zagruzhen.\n\n"
                f"{TOKEN_ERROR}\n\n"
                f"Fail tokena: {TOKEN_FILE}"
            )
            info.setWordWrap(True)
            info.setMargin(20)
            self.setCentralWidget(info)
            return

        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.instruments_controller = InstrumentsController(TOKEN, parent=self)
        self.trading_context = TradingContext(parent=self)
        self.quotes_hub = QuotesHub(TOKEN, self.instruments_controller, parent=self)
        self.positions_hub = PositionsHub(
            TOKEN,
            self.instruments_controller,
            self.trading_context,
            parent=self,
        )
        self.quotes_hub.error.connect(self._on_quotes_error)
        self.quotes_hub.start()
        self.positions_hub.start()

        self.home_tab = HomeTab(instruments_controller=self.instruments_controller)
        self.sandbox_trading_tab = SandboxTradingTab(
            instruments_controller=self.instruments_controller,
            quotes_hub=self.quotes_hub,
            trading_context=self.trading_context,
        )
        self.robots_tab = RobotsTab(
            instruments_controller=self.instruments_controller,
            quotes_hub=self.quotes_hub,
            trading_context=self.trading_context,
            positions_hub=self.positions_hub,
        )
        self.journal_tab = JournalTab(trading_context=self.trading_context)
        self.events_tab = EventsTab(self.trading_context, self.instruments_controller)

        self.tabs.addTab(self.home_tab, "Инструманты")
        self.tabs.addTab(self.sandbox_trading_tab, "Торговля")
        self.tabs.addTab(self.robots_tab, "Роботы")
        self.tabs.addTab(self.journal_tab, "Журнал")
        self.tabs.addTab(self.events_tab, "События")

        if AccountTab is not None:
            self.account_tab = AccountTab()
            self.tabs.addTab(self.account_tab, "Счета")

        self._hb_t0 = perf_counter()
        self._hb_qtimer = QtCore.QTimer(self)
        self._hb_qtimer.setInterval(5000)
        self._hb_qtimer.timeout.connect(self._heartbeat)
        self._hb_qtimer.start()

    def _heartbeat(self):
        dt = perf_counter() - self._hb_t0
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(
            f"[ui-heartbeat:{ts}] alive uptime={dt:.1f}s "
            f"tab={self.tabs.currentIndex() if hasattr(self, 'tabs') else -1}"
        )

    def _on_tab_changed(self, index: int):
        if self.account_tab is None:
            return
        if self.tabs.widget(index) is self.account_tab:
            self.account_tab.refresh_accounts()

    def _on_quotes_error(self, err: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[quotes-error:{ts}] {err}")

    def closeEvent(self, event):
        try:
            if hasattr(self, "_hb_qtimer") and self._hb_qtimer is not None:
                self._hb_qtimer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "events_tab") and self.events_tab is not None:
                self.events_tab.stop_stream(wait_ms=4000)
        except Exception:
            pass
        try:
            if hasattr(self, "quotes_hub") and self.quotes_hub is not None:
                self.quotes_hub.stop(wait_ms=3000)
        except Exception:
            pass
        try:
            if hasattr(self, "positions_hub") and self.positions_hub is not None:
                self.positions_hub.stop(wait_ms=3000)
        except Exception:
            pass
        try:
            if self.home_tab is not None:
                self.home_tab.stop_loading()
        except Exception:
            pass
        try:
            if self.sandbox_trading_tab is not None:
                self.sandbox_trading_tab.stop()
        except Exception:
            pass
        try:
            if self.journal_tab is not None:
                self.journal_tab.stop()
        except Exception:
            pass
        super().closeEvent(event)