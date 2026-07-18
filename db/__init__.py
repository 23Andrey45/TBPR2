# TBPR2 Database Module
"""
Модуль для работы с SQLite базой данных.
Хранит ордера, сделки (fills) и другую историю торговли.
"""

__all__ = [
    'Database',
    'get_db',
    'init_db',
    'close_db',
    'Order',
    'Fill',
    'OrderRepository',
    'FillRepository',
]

# Lazy imports to avoid circular dependencies
def __getattr__(name):
    if name in ('Database', 'get_db', 'init_db', 'close_db'):
        from db.database import Database, get_db, init_db, close_db
        return locals()[name]
    elif name == 'Order':
        from db.models import Order
        return Order
    elif name == 'Fill':
        from db.models import Fill
        return Fill
    elif name in ('OrderRepository', 'FillRepository'):
        from db.repositories import OrderRepository, FillRepository
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
