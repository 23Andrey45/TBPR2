# TBPR2 Database Module

SQLite база данных для хранения истории торговли.

## 📁 Структура

```
db/
├── __init__.py          # Экспорт модуля
├── database.py          # Подключение к SQLite, миграции
├── models.py            # Модели данных (Order, Fill)
├── repositories.py      # DAO слой для CRUD операций
└── README.md            # Этот файл
```

## 🗄️ Схема базы данных

### Таблица `orders`
| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER | Primary key |
| local_id | TEXT | Уникальный ID (UUID) |
| account_id | TEXT | ID аккаунта |
| figi | TEXT | FIGI инструмента |
| ticker | TEXT | Тикер |
| side | TEXT | BUY/SELL |
| order_type | TEXT | LIMIT/MARKET |
| lots_requested | INTEGER | Запрошено лотов |
| lots_executed | INTEGER | Исполнено лотов |
| price | TEXT | Цена |
| order_id | TEXT | ID ордера на сервере |
| server_status | TEXT | Статус от сервера |
| status_ui | TEXT | Статус для UI |
| message | TEXT | Сообщение |
| created_at | TEXT | Время создания (ISO) |
| updated_at | TEXT | Время обновления (ISO) |

### Таблица `fills`
| Поле | Тип | Описание |
|------|-----|----------|
| id | INTEGER | Primary key |
| deal_id | TEXT | Уникальный ID сделки |
| account_id | TEXT | ID аккаунта |
| figi | TEXT | FIGI инструмента |
| ticker | TEXT | Тикер |
| side | TEXT | BUY/SELL |
| lots | INTEGER | Количество лотов |
| price | TEXT | Цена |
| status | TEXT | Статус |
| order_id | TEXT | ID родительского ордера |
| source | TEXT | Источник (server/cache) |
| time | TEXT | Время сделки (ISO) |

## 🚀 Использование

### Инициализация
```python
from db import init_db, get_db

# Инициализировать БД
db = init_db(Path("data/tbpr.db"))

# Или получить существующий экземпляр
db = get_db()
```

### Работа с ордерами
```python
from db import Order, OrderRepository

# Создать ордер
order = Order(
    local_id="uuid-123",
    account_id="123456",
    figi="BBG004730ZK0",
    ticker="SBER",
    side="BUY",
    order_type="LIMIT",
    lots_requested=10,
    price="250.00",
    status_ui="Активна",
    created_at=Order.now_iso()
)

# Сохранить
OrderRepository.insert(order)

# Получить все ордера аккаунта
orders = OrderRepository.get_all("123456")

# Получить активные ордера
active = OrderRepository.get_active("123456")

# Обновить статус
OrderRepository.update_status("uuid-123", "Исполнена", lots_executed=10)

# Удалить
OrderRepository.delete_by_local_id("uuid-123")
```

### Работа с исполнениями
```python
from db import Fill, FillRepository

# Создать исполнение
fill = Fill(
    deal_id="deal-456",
    account_id="123456",
    figi="BBG004730ZK0",
    ticker="SBER",
    side="BUY",
    lots=10,
    price="250.00",
    status="Исполнена",
    time=Order.now_iso()
)

# Сохранить
FillRepository.insert(fill)

# Сохранить много
FillRepository.insert_many([fill1, fill2, fill3])

# Получить за 3 дня
fills = FillRepository.get_all("123456", days=3)
```

### Очистка старых данных
```python
# Удалить ордера старше 30 дней
OrderRepository.clear_old(30)

# Удалить исполнения старше 30 дней
FillRepository.clear_old(30)
```

## 🔧 Настройки SQLite

По умолчанию используются оптимальные настройки:
- **WAL режим** (Write-Ahead Logging) для лучшей производительности
- **synchronous=NORMAL** для баланса между скоростью и надёжностью
- **timeout=30s** для ожидания блокировок

## 📊 Индексы

Созданы автоматически для ускорения поиска:
- `idx_orders_account` - по account_id
- `idx_orders_figi` - по figi
- `idx_orders_created` - по created_at
- `idx_orders_status` - по status_ui
- `idx_fills_account` - по account_id
- `idx_fills_figi` - по figi
- `idx_fills_time` - по time

## 🛡️ Безопасность

- Все операции выполняются в транзакциях
- ACID гарантии
- Foreign keys включены
- Поддержка concurrent access через WAL

## 📝 Миграции

При изменении схемы:
1. Обновите `_create_tables()` в `database.py`
2. Добавьте миграционную функцию
3. Вызовите в ` _initialize()`

## 🐛 Отладка

Включите логирование:
```python
import sys
# Логи будут выводиться в консоль
```

Файл БД: `data/tbpr.db`

Файлы WAL: `data/tbpr.db-wal`, `data/tbpr.db-shm`
