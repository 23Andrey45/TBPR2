# db/repositories.py
"""
Репозитории для работы с базой данных.
Все методы работают асинхронно и не блокируют UI.
"""

from __future__ import annotations

import sqlite3
from typing import Optional, Any
from datetime import datetime, timezone, timedelta

from db.database import get_db
from db.models import Order, Fill

import sys


class OrderRepository:
    """Репозиторий для работы с ордерами."""

    @staticmethod
    def insert(order: Order) -> bool:
        """Вставить новый ордер."""
        try:
            db = get_db()
            cursor = db._execute("""
                INSERT OR REPLACE INTO orders 
                (local_id, account_id, figi, ticker, side, order_type, 
                 lots_requested, lots_executed, price, order_id, 
                 server_status, status_ui, message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.local_id,
                order.account_id,
                order.figi,
                order.ticker,
                order.side,
                order.order_type,
                order.lots_requested,
                order.lots_executed,
                order.price,
                order.order_id,
                order.server_status,
                order.status_ui,
                order.message,
                order.created_at,
                order.updated_at,
            ))
            db._commit()
            print(f"[DB-Order] Inserted: {order.local_id}")
            sys.stdout.flush()
            return True
        except Exception as e:
            print(f"[DB-Order] ERROR insert: {e}")
            sys.stdout.flush()
            return False

    @staticmethod
    def update_status(local_id: str, status_ui: str, server_status: str = "", lots_executed: int = 0) -> bool:
        """Обновить статус ордера."""
        try:
            db = get_db()
            updated_at = datetime.now(timezone.utc).isoformat()
            db._execute("""
                UPDATE orders 
                SET status_ui = ?, server_status = ?, lots_executed = ?, updated_at = ?
                WHERE local_id = ?
            """, (status_ui, server_status, lots_executed, updated_at, local_id))
            db._commit()
            return True
        except Exception as e:
            print(f"[DB-Order] ERROR update: {e}")
            sys.stdout.flush()
            return False

    @staticmethod
    def delete_by_local_id(local_id: str) -> bool:
        """Удалить ордер по local_id."""
        try:
            db = get_db()
            db._execute("DELETE FROM orders WHERE local_id = ?", (local_id,))
            db._commit()
            print(f"[DB-Order] Deleted: {local_id}")
            sys.stdout.flush()
            return True
        except Exception as e:
            print(f"[DB-Order] ERROR delete: {e}")
            sys.stdout.flush()
            return False

    @staticmethod
    def get_all(account_id: str = "") -> list[Order]:
        """Получить все ордера (опционально по account_id)."""
        try:
            db = get_db()
            if account_id:
                cursor = db._execute(
                    "SELECT * FROM orders WHERE account_id = ? ORDER BY created_at DESC",
                    (account_id,)
                )
            else:
                cursor = db._execute("SELECT * FROM orders ORDER BY created_at DESC")

            rows = cursor.fetchall()
            orders = [Order(
                id=row["id"],
                local_id=row["local_id"],
                account_id=row["account_id"],
                figi=row["figi"],
                ticker=row["ticker"],
                side=row["side"],
                order_type=row["order_type"],
                lots_requested=row["lots_requested"],
                lots_executed=row["lots_executed"],
                price=row["price"],
                order_id=row["order_id"],
                server_status=row["server_status"],
                status_ui=row["status_ui"],
                message=row["message"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            ) for row in rows]

            print(f"[DB-Order] Retrieved {len(orders)} orders")
            sys.stdout.flush()
            return orders
        except Exception as e:
            print(f"[DB-Order] ERROR get_all: {e}")
            sys.stdout.flush()
            return []

    @staticmethod
    def get_active(account_id: str = "") -> list[Order]:
        """Получить активные ордера."""
        try:
            db = get_db()
            if account_id:
                cursor = db._execute(
                    """SELECT * FROM orders 
                       WHERE account_id = ? AND status_ui != 'Исполнена' 
                       AND status_ui != 'Отменена' AND status_ui != 'Отклонена'
                       ORDER BY created_at DESC""",
                    (account_id,)
                )
            else:
                cursor = db._execute(
                    """SELECT * FROM orders 
                       WHERE status_ui != 'Исполнена' 
                       AND status_ui != 'Отменена' AND status_ui != 'Отклонена'
                       ORDER BY created_at DESC"""
                )

            rows = cursor.fetchall()
            orders = [Order(
                id=row["id"],
                local_id=row["local_id"],
                account_id=row["account_id"],
                figi=row["figi"],
                ticker=row["ticker"],
                side=row["side"],
                order_type=row["order_type"],
                lots_requested=row["lots_requested"],
                lots_executed=row["lots_executed"],
                price=row["price"],
                order_id=row["order_id"],
                server_status=row["server_status"],
                status_ui=row["status_ui"],
                message=row["message"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            ) for row in rows]

            print(f"[DB-Order] Retrieved {len(orders)} active orders")
            sys.stdout.flush()
            return orders
        except Exception as e:
            print(f"[DB-Order] ERROR get_active: {e}")
            sys.stdout.flush()
            return []

    @staticmethod
    def clear_old(days: int = 30) -> int:
        """Удалить старые ордера."""
        try:
            db = get_db()
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            cursor = db._execute(
                "DELETE FROM orders WHERE created_at < ?",
                (cutoff,)
            )
            db._commit()
            deleted = cursor.rowcount
            print(f"[DB-Order] Cleared {deleted} old orders")
            sys.stdout.flush()
            return deleted
        except Exception as e:
            print(f"[DB-Order] ERROR clear_old: {e}")
            sys.stdout.flush()
            return 0


class FillRepository:
    """Репозиторий для работы с исполнениями (сделками)."""

    @staticmethod
    def insert(fill: Fill) -> bool:
        """Вставить новое исполнение."""
        try:
            db = get_db()
            cursor = db._execute("""
                INSERT OR REPLACE INTO fills 
                (deal_id, account_id, figi, ticker, side, lots, price, 
                 status, order_id, source, time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fill.deal_id,
                fill.account_id,
                fill.figi,
                fill.ticker,
                fill.side,
                fill.lots,
                fill.price,
                fill.status,
                fill.order_id,
                fill.source,
                fill.time,
            ))
            db._commit()
            print(f"[DB-Fill] Inserted: {fill.deal_id}")
            sys.stdout.flush()
            return True
        except Exception as e:
            print(f"[DB-Fill] ERROR insert: {e}")
            sys.stdout.flush()
            return False

    @staticmethod
    def insert_many(fills: list[Fill]) -> int:
        """Вставить много исполнений."""
        try:
            db = get_db()
            data = [(
                f.deal_id,
                f.account_id,
                f.figi,
                f.ticker,
                f.side,
                f.lots,
                f.price,
                f.status,
                f.order_id,
                f.source,
                f.time,
            ) for f in fills]

            cursor = db._execute("BEGIN")
            cursor.executemany("""
                INSERT OR REPLACE INTO fills 
                (deal_id, account_id, figi, ticker, side, lots, price, 
                 status, order_id, source, time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
            db._commit()

            print(f"[DB-Fill] Inserted {len(fills)} fills")
            sys.stdout.flush()
            return len(fills)
        except Exception as e:
            print(f"[DB-Fill] ERROR insert_many: {e}")
            sys.stdout.flush()
            return 0

    @staticmethod
    def get_all(account_id: str = "", days: int = 3) -> list[Fill]:
        """Получить все исполнения за период."""
        try:
            db = get_db()
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            if account_id:
                cursor = db._execute(
                    """SELECT * FROM fills 
                       WHERE account_id = ? AND time >= ?
                       ORDER BY time DESC""",
                    (account_id, cutoff)
                )
            else:
                cursor = db._execute(
                    """SELECT * FROM fills 
                       WHERE time >= ?
                       ORDER BY time DESC""",
                    (cutoff,)
                )

            rows = cursor.fetchall()
            fills = [Fill(
                id=row["id"],
                deal_id=row["deal_id"],
                account_id=row["account_id"],
                figi=row["figi"],
                ticker=row["ticker"],
                side=row["side"],
                lots=row["lots"],
                price=row["price"],
                status=row["status"],
                order_id=row["order_id"],
                source=row["source"],
                time=row["time"],
            ) for row in rows]

            print(f"[DB-Fill] Retrieved {len(fills)} fills")
            sys.stdout.flush()
            return fills
        except Exception as e:
            print(f"[DB-Fill] ERROR get_all: {e}")
            sys.stdout.flush()
            return []

    @staticmethod
    def clear_old(days: int = 30) -> int:
        """Удалить старые исполнения."""
        try:
            db = get_db()
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            cursor = db._execute(
                "DELETE FROM fills WHERE time < ?",
                (cutoff,)
            )
            db._commit()
            deleted = cursor.rowcount
            print(f"[DB-Fill] Cleared {deleted} old fills")
            sys.stdout.flush()
            return deleted
        except Exception as e:
            print(f"[DB-Fill] ERROR clear_old: {e}")
            sys.stdout.flush()
            return 0
