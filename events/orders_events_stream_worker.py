# events/orders_events_stream_worker.py
"""
Заглушка для OrdersEventsStreamWorker.
"""

from PyQt6 import QtCore


class OrdersEventsStreamWorker(QtCore.QObject):
    event_received = QtCore.pyqtSignal(object)
    status_changed = QtCore.pyqtSignal(str)
    subscription_info = QtCore.pyqtSignal(object)
    stream_closed = QtCore.pyqtSignal()

    def __init__(self, token: str, account_id: str, parent=None):
        super().__init__(parent)
        self.token = token
        self.account_id = account_id
        self._stopping = False

    def stop(self):
        self._stopping = True

    @QtCore.pyqtSlot()
    def run(self):
        self.status_changed.emit(f"Orders stream: account={self.account_id}")
        self.subscription_info.emit({
            "target": "orders",
            "service": "tinkoff.grpc",
            "method": "GetOrdersStream",
            "attempt": 1,
            "account_id": self.account_id,
        })
        # Заглушка - не подключаемся реально
        self.stream_closed.emit()