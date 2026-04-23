import sqlite3
import os
import threading
from datetime import datetime
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "./mervalbot.db")

_lock = threading.Lock()

def _get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _init_db():
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            entry_price REAL,
            sl_price REAL,
            tp_price REAL,
            plazo TEXT,
            is_paper INTEGER,
            status TEXT,
            close_price REAL,
            pnl_ars REAL,
            pnl_pct REAL,
            entry_ts TEXT,
            close_ts TEXT,
            reason TEXT,
            order_id TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT,
            symbol TEXT,
            action TEXT,
            entry_price REAL,
            sl_price REAL,
            tp_price REAL,
            reason TEXT,
            confidence REAL,
            ts TEXT,
            executed INTEGER
        )
        """)
        conn.commit()
        conn.close()

_init_db()

def open_trade(signal, quantity, order_id=None):
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        now = datetime.utcnow().isoformat()
        c.execute(
            """
            INSERT INTO trades (strategy_id, symbol, side, quantity, entry_price, sl_price, tp_price, plazo, is_paper, status, entry_ts, reason, order_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.strategy_id,
                signal.symbol,
                signal.action,
                quantity,
                signal.entry_price,
                signal.sl_price,
                signal.tp_price,
                getattr(signal, "plazo", "t2"),
                1,  # is_paper always 1 for now
                "OPEN",
                now,
                signal.reason,
                order_id,
            ),
        )
        trade_id = c.lastrowid
        conn.commit()
        conn.close()
        return trade_id

def close_trade(trade_id, close_price, reason):
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        now = datetime.utcnow().isoformat()
        c.execute("SELECT entry_price, quantity FROM trades WHERE id=?", (trade_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return None
        entry_price = row["entry_price"]
        quantity = row["quantity"]
        pnl_ars = (close_price - entry_price) * quantity
        commission = (entry_price + close_price) * quantity * 0.006
        pnl_ars = pnl_ars - commission
        pnl_pct = (close_price - entry_price) / entry_price * 100 if entry_price else 0
        c.execute(
            """
            UPDATE trades SET status=?, close_price=?, pnl_ars=?, pnl_pct=?, close_ts=?, reason=? WHERE id=?
            """,
            ("CLOSED", close_price, pnl_ars, pnl_pct, now, reason, trade_id),
        )
        conn.commit()
        conn.close()
        return pnl_ars

def get_open_trades(strategy_id=None):
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        if strategy_id:
            c.execute("SELECT * FROM trades WHERE status='OPEN' AND strategy_id=?", (strategy_id,))
        else:
            c.execute("SELECT * FROM trades WHERE status='OPEN'")
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]

def get_stats(strategy_id):
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM trades WHERE strategy_id=?", (strategy_id,))
        n_trades = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM trades WHERE strategy_id=? AND pnl_ars > 0", (strategy_id,))
        n_win = c.fetchone()[0]
        c.execute("SELECT SUM(pnl_ars) FROM trades WHERE strategy_id=?", (strategy_id,))
        pnl_ars = c.fetchone()[0] or 0
        win_rate = n_win / n_trades if n_trades else 0
        conn.close()
        return {
            "n_trades": n_trades,
            "win_rate": win_rate,
            "pnl_ars": pnl_ars,
        }

def log_signal(signal, executed: bool):
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        now = datetime.utcnow().isoformat()
        c.execute(
            """
            INSERT INTO signals (strategy_id, symbol, action, entry_price, sl_price, tp_price, reason, confidence, ts, executed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.strategy_id,
                signal.symbol,
                signal.action,
                signal.entry_price,
                signal.sl_price,
                signal.tp_price,
                signal.reason,
                signal.confidence,
                now,
                int(executed),
            ),
        )
        conn.commit()
        conn.close()
