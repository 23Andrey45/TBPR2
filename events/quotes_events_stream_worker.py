# events/quotes_events_stream_worker.py
"""
Заглушка для QuotesEventsStreamWorker.
"""

from PyQt6 import QtCore


class QuotesEventsStreamWorker(QtCore.QObject):
    quote_received = QtCore.pyqtSignal(object)
    status_changed = QtCore.pyqtSignal(str)
    subscription_info = QtCore.pyqtSignal(object)
    stream_closed = QtCore.pyqtSignal()

    def __init__(self, token: str, figis: list, parent=None):
        super().__init__(parent)
        self.token = token
        self.figis = figis
        self._stopping = False

    def stop(self):
        self._stopping = True

    @QtCore.pyqtSlot()
    def run(self):
        self.status_changed.emit(f"Quotes stream: {len(self.figis)} figis")
        self.subscription_info.emit({
            "figis": self.figis,
            "service": "tinkoff.grpc",
            "method": "GetCandles",
        })
        # Заглушка - не подключаемся реально
        self.stream_closed.emit()