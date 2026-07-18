# db/database.py
"""
Подключение к SQLite базе данных и управление миграциями.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Generator

import sys

print("[DB] Initializing database module...")
sys.stdout.flush()


class Database:
    """Класс для управления подключением к SQLite."""

    _instance: Optional['Database'] = None
    _initialized: bool = False

    def __new__(cls, db_path: Optional[Path] = None) -> 'Database':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: Optional[Path] = None):
        if Database._initialized:
            return

        if db_path is None:
            from app.config import DATA_DIR
            db_path = DATA_DIR / "tbpr.db"

        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = False

        print(f"[DB] Database path: {self.db_path}")
        sys.stdout.flush()

        self._initialize()
        Database._initialized = True

    def _initialize(self) -> None:
        """Инициализация подключения и создание таблиц."""
        try:
            self._connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0
            )
            self._connection.row_factory = sqlite3.Row
            print("[DB] Connection established")
            sys.stdout.flush()

            # Включаем WAL режим для лучшей производительности
            self._execute("PRAGMA journal_mode=WAL")
            self._execute("PRAGMA synchronous=NORMAL")
            self._execute("PRAGMA foreign_keys=ON")

            # Создаём таблицы
            self._create_tables()
            print("[DB] Tables created/verified")
            sys.stdout.flush()

        except Exception as e:
            print(f"[DB] ERROR during initialization: {e}")
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            raise

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Выполнить SQL запрос."""
        if self._connection is None:
            raise RuntimeError("Database not initialized")

        cursor = self._connection.cursor()
        cursor.execute(sql, params)
        return cursor

    def _commit(self) -> None:
        """Закоммитить транзакцию."""
        if self._connection is not None:
            self._connection.commit()

    def _create_tables(self) -> None:
        """Создать таблицы если их нет."""
        # Таблица ордеров
        self._execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                local_id TEXT UNIQUE NOT NULL,
                account_id TEXT NOT NULL,
                figi TEXT NOT NULL,
                ticker TEXT,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                lots_requested INTEGER,
                lots_executed INTEGER DEFAULT 0,
                price TEXT,
                order_id TEXT,
                server_status TEXT,
                status_ui TEXT,
                message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)

        # Таблица исполнений (fills)
        self._execute("""
            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT UNIQUE NOT NULL,
                account_id TEXT NOT NULL,
                figi TEXT NOT NULL,
                ticker TEXT,
                side TEXT NOT NULL,
                lots INTEGER,
                price TEXT,
                status TEXT,
                order_id TEXT,
                source TEXT,
                time TEXT NOT NULL
            )
        """)

        # Создаём индексы
        self._execute("CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account_id)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_orders_figi ON orders(figi)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status_ui)")

        self._execute("CREATE INDEX IF NOT EXISTS idx_fills_account ON fills(account_id)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_fills_figi ON fills(figi)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_fills_time ON fills(time)")

        self._commit()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """Контекстный менеджер для транзакций."""
        cursor = self._execute("BEGIN")
        try:
            yield cursor
            self._commit()
        except Exception as e:
            self._execute("ROLLBACK")
            raise

    def get_connection(self) -> sqlite3.Connection:
        """Получить подключение."""
        if self._connection is None:
            raise RuntimeError("Database not initialized")
        return self._connection

    def close(self) -> None:
        """Закрыть подключение."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            print("[DB] Connection closed")
            sys.stdout.flush()


# Глобальный экземпляр
_db_instance: Optional[Database] = None


def get_db(db_path: Optional[Path] = None) -> Database:
    """Получить экземпляр базы данных (singleton)."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(db_path)
    return _db_instance


def init_db(db_path: Optional[Path] = None) -> Database:
    """Инициализировать базу данных."""
    global _db_instance
    _db_instance = Database(db_path)
    return _db_instance


def close_db() -> None:
    """Закрыть базу данных."""
    global _db_instance
    if _db_instance is not None:
        _db_instance.close()
        _db_instance = None


print("[DB] Module loaded successfully")
sys.stdout.flush()
