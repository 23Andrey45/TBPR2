from datetime import datetime, timezone
from time import perf_counter

from PyQt6 import QtCore, QtWidgets

from app.config import TOKEN, TOKEN_ERROR, TOKEN_FILE, REAL_TOKEN
from app.app_context import init_app_context
from instruments.instruments_controller import InstrumentsController
from market_data.positions_hub import PositionsHub
from market_data.quotes_hub import QuotesHub
from instruments.tab_instruments import InstrumentsTab
from events.tab_events import EventsTab
from journal.tab_journal import JournalTab
from robots.tab_robots import RobotsTab
from history.tab_history import HistoryTab
from sandbox_trading.tab_sandbox_trading import SandboxTradingTab

try:
    from account.tab_account import AccountTab
except Exception:
    AccountTab = None

try:
    from real_account.tab_real_account import RealAccountTab

    REAL_ACCOUNT_AVAILABLE = True
    print("[MainWindow] RealAccountTab loaded successfully")
except Exception as e:
    RealAccountTab = None
    REAL_ACCOUNT_AVAILABLE = False
    print(f"[MainWindow] ERROR loading RealAccountTab: {e}")
    import traceback

    traceback.print_exc()

try:
    from debug.tab_debug import DebugTab

    DEBUG_TAB_AVAILABLE = True
    print("[MainWindow] DebugTab loaded successfully")
except Exception as e:
    DebugTab = None
    DEBUG_TAB_AVAILABLE = False
    print(f"[MainWindow] ERROR loading DebugTab: {e}")
    import traceback

    traceback.print_exc()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Moe приложение")
        self.resize(1400, 800)

        self.home_tab = None
        self.journal_tab = None
        self.account_tab = None
        self.real_account_tab = None
        self.debug_tab = None

        # Создаём контекст приложения
        self.app_context = init_app_context(sandbox_token=TOKEN, real_token=REAL_TOKEN)
        print(f"[MainWindow] AppContext initialized: {self.app_context}")

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

        # Все подсистемы используют app_context
        self.quotes_hub = QuotesHub(TOKEN, self.instruments_controller, app_context=self.app_context, parent=self)
        self.positions_hub = PositionsHub(
            TOKEN,
            self.instruments_controller,
            self.app_context,
            parent=self,
        )
        self.quotes_hub.error.connect(self._on_quotes_error)
        self.quotes_hub.start()
        self.positions_hub.start()

        self.instruments_tab = InstrumentsTab(instruments_controller=self.instruments_controller)
        self.robots_tab = RobotsTab(
            instruments_controller=self.instruments_controller,
            quotes_hub=self.quotes_hub,
            app_context=self.app_context,
            positions_hub=self.positions_hub,
        )
        self.history_tab = HistoryTab(app_context=self.app_context)
        self.journal_tab = JournalTab(app_context=self.app_context)
        self.events_tab = EventsTab(self.app_context, self.instruments_controller)

        self.tabs.addTab(self.instruments_tab, "Инструменты")
        self.tabs.addTab(self.robots_tab, "Роботы")
        self.tabs.addTab(self.history_tab, "История")
        self.tabs.addTab(self.journal_tab, "Журнал")
        self.tabs.addTab(self.events_tab, "События")

        # Вкладка "Торговля (песочница)"
        self.sandbox_trading_tab = SandboxTradingTab(
            instruments_controller=self.instruments_controller,
            quotes_hub=self.quotes_hub,
            app_context=self.app_context,
        )
        self.tabs.addTab(self.sandbox_trading_tab, "Торговля (песочница)")

        if AccountTab is not None:
            self.account_tab = AccountTab()
            self.tabs.addTab(self.account_tab, "Счета")

        # Вкладка реального счёта
        if REAL_ACCOUNT_AVAILABLE:
            self.real_account_tab = RealAccountTab(
                instruments_controller=self.instruments_controller,
                quotes_hub=self.quotes_hub,
                app_context=self.app_context,
            )
            self.tabs.addTab(self.real_account_tab, "Реальный счёт")

        # Вкладка отладки
        if DEBUG_TAB_AVAILABLE:
            self.debug_tab = DebugTab(app_context=self.app_context)
            self.tabs.addTab(self.debug_tab, "🔍 Отладка")

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

        # Отладочная вкладка уже получает обновления через app_context

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
            if self.instruments_tab is not None:
                self.instruments_tab.stop_loading()
        except Exception:
            pass
        try:
            if self.sandbox_trading_tab is not None:
                self.sandbox_trading_tab.stop()
        except Exception:
            pass
        try:
            if self.history_tab is not None:
                # HistoryTab не требует специальной остановки
                pass
        except Exception:
            pass
        try:
            if self.journal_tab is not None:
                self.journal_tab.stop()
        except Exception:
            pass

        # Закрываем базу данных
        try:
            from db import close_db
            close_db()
            print("[MainWindow] Database closed")
        except Exception as e:
            print(f"[MainWindow] DB close error: {e}")

        super().closeEvent(event)