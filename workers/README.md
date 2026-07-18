# TBPR2 Workers

Общие воркеры для всего приложения. Все воркеры работают в отдельных `QThread` и не блокируют UI.

## 📁 Структура

```
workers/
├── __init__.py              # Экспорт всех воркеров
├── account_workers.py       # Аккаунты и баланс
├── order_workers.py         # Ордера (размещение, отмена, статусы)
└── README.md                # Этот файл
```

## 🚀 Использование

### Импорт
```python
from workers import (
    SandboxAccountsLoader,
    SandboxMoneyBalanceLoader,
    SandboxPostLimitOrderLoader,
    SandboxActiveOrdersLoader,
    CancelSandboxOrderWorker,
)
```

### Запуск воркера
```python
def _run_worker(self, worker: QtCore.QObject, on_loaded=None):
    thread = QtCore.QThread(self)
    worker.moveToThread(thread)
    
    if hasattr(worker, "loaded") and on_loaded is not None:
        worker.loaded.connect(on_loaded, QtCore.Qt.ConnectionType.QueuedConnection)
    
    if hasattr(worker, "finished"):
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
    
    thread.started.connect(worker.run)
    thread.finished.connect(thread.deleteLater)
    
    self._jobs.append((thread, worker))
    thread.start()
```

### Пример: Загрузка аккаунтов
```python
self._run_worker(
    SandboxAccountsLoader(TOKEN),
    self._on_accounts_loaded
)

def _on_accounts_loaded(self, accounts: list):
    for acc in accounts:
        print(f"Account: {acc.account_id}")
```

### Пример: Размещение ордера
```python
worker = SandboxPostLimitOrderLoader(
    token=TOKEN,
    account_id="123456",
    figi="BBG004730ZK0",
    direction="BUY",
    lots=10,
    price_str="250.00"
)

self._run_worker(worker, self._on_order_result)

def _on_order_result(self, res: PlaceOrderAttempt):
    if res.sent:
        print(f"Order placed: {res.order_id}")
    else:
        print(f"Order failed: {res.message}")
```

## 📊 Доступные воркеры

### Account Workers

| Воркер | Описание |
|--------|----------|
| `SandboxAccountsLoader` | Загрузка списка sandbox аккаунтов |
| `SandboxMoneyBalanceLoader` | Загрузка денежного баланса |

### Order Workers

| Воркер | Описание |
|--------|----------|
| `SandboxPostLimitOrderLoader` | Размещение LIMIT ордера |
| `SandboxActiveOrdersLoader` | Загрузка активных ордеров |
| `CancelSandboxOrderWorker` | Отмена ордера |
| `RecentDealsLoader` | История сделок |
| `OrderStatesLoader` | Статусы ордеров |

## 🎯 Принципы

1. **Один воркер = одна операция**
2. **Нет блокировок UI** - всё в отдельных потоках
3. **Переиспользование** - воркеры общие для всех вкладок
4. **Безопасность** - передача данных только через сигналы

## 🛡️ Обработка ошибок

Все воркеры отправляют ошибки через сигнал `error`:

```python
worker.error.connect(self._on_worker_error)

def _on_worker_error(self, tb: str):
    print(f"Worker error: {tb}")
```

## 📝 Добавление нового воркера

1. Создать класс в соответствующем файле (`account_workers.py` или `order_workers.py`)
2. Унаследовать от `QtCore.QObject`
3. Добавить сигналы `loaded`, `error`, `finished`
4. Реализовать метод `run()` с декоратором `@QtCore.pyqtSlot()`
5. Добавить экспорт в `__init__.py`

### Пример
```python
class MyNewWorker(QtCore.QObject):
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, token: str, param: str):
        super().__init__()
        self.token = token
        self.param = param

    @QtCore.pyqtSlot()
    def run(self):
        try:
            result = do_something(self.token, self.param)
            self.loaded.emit(result)
        except Exception:
            import traceback
            self.error.emit(traceback.format_exc())
        finally:
            self.finished.emit()
```
