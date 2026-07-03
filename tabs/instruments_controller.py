# tabs/instruments_controller.py
from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore

from app.config import FAVORITES_FILE
from core.favorites_repo import load_favorites, save_favorites
from core.instruments_catalog import InstrumentInfo
from tabs.workers import InstrumentsCatalogLoader


class InstrumentsController(QtCore.QObject):
    status_changed = QtCore.pyqtSignal(str)
    loading_changed = QtCore.pyqtSignal(bool)

    shares_updated = QtCore.pyqtSignal(object)  # list[InstrumentInfo]
    bonds_updated = QtCore.pyqtSignal(object)   # list[InstrumentInfo]
    etfs_updated = QtCore.pyqtSignal(object)    # list[InstrumentInfo]

    favorites_updated = QtCore.pyqtSignal(object)  # list[InstrumentInfo]
    error = QtCore.pyqtSignal(str)

    def __init__(self, token: str, parent=None):
        super().__init__(parent)
        self.token = token

        self._shares: list[InstrumentInfo] = []
        self._bonds: list[InstrumentInfo] = []
        self._etfs: list[InstrumentInfo] = []

        self._favorites: dict[str, InstrumentInfo] = load_favorites(FAVORITES_FILE)

        self._thread: Optional[QtCore.QThread] = None
        self._worker: Optional[InstrumentsCatalogLoader] = None

    def favorites(self) -> list[InstrumentInfo]:
        return sorted(self._favorites.values(), key=lambda x: (x.kind, x.ticker, x.name))

    def is_favorite(self, info: InstrumentInfo) -> bool:
        return info.fav_key() in self._favorites

    def add_favorite(self, info: InstrumentInfo):
        self._favorites[info.fav_key()] = info
        save_favorites(FAVORITES_FILE, self._favorites)
        self.favorites_updated.emit(self.favorites())

    def remove_favorite(self, info: InstrumentInfo):
        self._favorites.pop(info.fav_key(), None)
        save_favorites(FAVORITES_FILE, self._favorites)
        self.favorites_updated.emit(self.favorites())

    def refresh(self):
        if self._thread and self._thread.isRunning():
            return

        self.loading_changed.emit(True)
        self.status_changed.emit("Загрузка инструментов (акции/облигации/ETF)...")

        self._thread = QtCore.QThread(self)
        self._worker = InstrumentsCatalogLoader(self.token)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.error.connect(self.error.emit)

        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_finished)

        self._thread.start()

    def emit_initial_state(self):
        # избранное можно показывать сразу, без refresh()
        self.favorites_updated.emit(self.favorites())

        # статус (пока каталоги не загружены)
        self.status_changed.emit(
            f"Избранное: {len(self._favorites)} | "
            f"Акции: {len(self._shares)} | Облигации: {len(self._bonds)} | ETF: {len(self._etfs)}"
        )

    @QtCore.pyqtSlot(object)
    def _on_loaded(self, payload: dict):
        self._shares = payload.get("share", []) or []
        self._bonds = payload.get("bond", []) or []
        self._etfs = payload.get("etf", []) or []

        self.shares_updated.emit(self._shares)
        self.bonds_updated.emit(self._bonds)
        self.etfs_updated.emit(self._etfs)

        self.favorites_updated.emit(self.favorites())
        self.status_changed.emit(f"Акции: {len(self._shares)} | Облигации: {len(self._bonds)} | ETF: {len(self._etfs)}")

    def _on_finished(self):
        self.loading_changed.emit(False)
        self._worker = None
        self._thread = None
