from __future__ import annotations

import sqlite3
from pathlib import Path
from time import time


class TradeStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    amount REAL NOT NULL,
                    price REAL NOT NULL,
                    order_id TEXT NOT NULL,
                    instance_name TEXT NOT NULL DEFAULT '',
                    strategy_name TEXT NOT NULL DEFAULT ''
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
            if "instance_name" not in columns:
                conn.execute("ALTER TABLE trades ADD COLUMN instance_name TEXT NOT NULL DEFAULT ''")
            if "strategy_name" not in columns:
                conn.execute("ALTER TABLE trades ADD COLUMN strategy_name TEXT NOT NULL DEFAULT ''")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_instance ON trades(instance_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_name)")

    def record_trade(self, symbol: str, side: str, amount: float, price: float, order_id: str,
                     instance_name: str = "", strategy_name: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trades (ts, symbol, side, amount, price, order_id, instance_name, strategy_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (time(), symbol, side, amount, price, order_id, instance_name, strategy_name),
            )

    def list_trades(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY id ASC").fetchall()
        return [dict(row) for row in rows]
