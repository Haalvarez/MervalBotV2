"""
DB del monitor — esquema nuevo, separado del trades.py legacy.
Tablas: ticks, macro, alerts, collector_errors.
Compatible con la misma DB SQLite (WAL ya habilitado).
"""
import sqlite3
import os
import threading
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "./mervalbot.db")

_lock = threading.Lock()


def _get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_monitor_db():
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS ticks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            symbol TEXT NOT NULL,
            source TEXT NOT NULL,
            last REAL,
            bid REAL,
            ask REAL,
            volume REAL
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts ON ticks(symbol, ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(ts DESC)")

        c.execute("""
        CREATE TABLE IF NOT EXISTS macro (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            mep_al30 REAL,
            mep_gd30 REAL,
            ccl_al30 REAL,
            caucion_1d REAL,
            caucion_7d REAL
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_macro_ts ON macro(ts DESC)")

        c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            symbol TEXT,
            kind TEXT,
            message TEXT,
            sent INTEGER DEFAULT 0
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts DESC)")

        c.execute("""
        CREATE TABLE IF NOT EXISTS collector_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            source TEXT,
            symbol TEXT,
            error TEXT
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_errors_ts ON collector_errors(ts DESC)")

        conn.commit()
        conn.close()


# -------------------------------------------------------------------- ticks

def save_tick(symbol: str, source: str, last: float,
              bid: Optional[float] = None, ask: Optional[float] = None,
              volume: Optional[float] = None, ts: Optional[str] = None):
    ts = ts or datetime.utcnow().isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO ticks (ts, symbol, source, last, bid, ask, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, symbol, source, last, bid, ask, volume),
        )
        conn.commit()
        conn.close()


def get_last_tick(symbol: str) -> Optional[dict]:
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM ticks WHERE symbol=? ORDER BY ts DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None


def get_ticks_since(symbol: str, since_iso_utc: str) -> list[dict]:
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM ticks WHERE symbol=? AND ts>=? ORDER BY ts ASC",
            (symbol, since_iso_utc),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_price_at_or_before(symbol: str, ts_iso_utc: str) -> Optional[float]:
    """Retorna el last conocido en o antes del timestamp. Para calcular deltas."""
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT last FROM ticks WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1",
            (symbol, ts_iso_utc),
        ).fetchone()
        conn.close()
        return row["last"] if row and row["last"] is not None else None


def get_latest_snapshot() -> list[dict]:
    """Último tick de cada símbolo."""
    with _lock:
        conn = _get_conn()
        rows = conn.execute("""
            SELECT t.* FROM ticks t
            INNER JOIN (
                SELECT symbol, MAX(ts) AS max_ts FROM ticks GROUP BY symbol
            ) latest ON t.symbol = latest.symbol AND t.ts = latest.max_ts
            ORDER BY t.symbol
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]


# -------------------------------------------------------------------- macro

def save_macro(mep_al30: Optional[float] = None, mep_gd30: Optional[float] = None,
               ccl_al30: Optional[float] = None,
               caucion_1d: Optional[float] = None, caucion_7d: Optional[float] = None,
               ts: Optional[str] = None):
    ts = ts or datetime.utcnow().isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO macro (ts, mep_al30, mep_gd30, ccl_al30, caucion_1d, caucion_7d) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, mep_al30, mep_gd30, ccl_al30, caucion_1d, caucion_7d),
        )
        conn.commit()
        conn.close()


def get_latest_macro() -> Optional[dict]:
    with _lock:
        conn = _get_conn()
        row = conn.execute("SELECT * FROM macro ORDER BY ts DESC LIMIT 1").fetchone()
        conn.close()
        return dict(row) if row else None


# -------------------------------------------------------------------- alerts

def save_alert(symbol: str, kind: str, message: str, sent: bool = False,
               ts: Optional[str] = None) -> int:
    ts = ts or datetime.utcnow().isoformat()
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO alerts (ts, symbol, kind, message, sent) VALUES (?, ?, ?, ?, ?)",
            (ts, symbol, kind, message, int(sent)),
        )
        alert_id = cur.lastrowid
        conn.commit()
        conn.close()
        return alert_id


def mark_alert_sent(alert_id: int):
    with _lock:
        conn = _get_conn()
        conn.execute("UPDATE alerts SET sent=1 WHERE id=?", (alert_id,))
        conn.commit()
        conn.close()


def get_recent_alerts(limit: int = 20) -> list[dict]:
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def last_alert_ts_for(symbol: str, kind: str) -> Optional[str]:
    """Para throttle: cuándo fue la última alerta de (symbol, kind)."""
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT ts FROM alerts WHERE symbol=? AND kind=? ORDER BY ts DESC LIMIT 1",
            (symbol, kind),
        ).fetchone()
        conn.close()
        return row["ts"] if row else None


# -------------------------------------------------------------------- errors

def log_collector_error(source: str, symbol: Optional[str], error: str):
    ts = datetime.utcnow().isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO collector_errors (ts, source, symbol, error) VALUES (?, ?, ?, ?)",
            (ts, source, symbol, error[:500]),
        )
        conn.commit()
        conn.close()


def get_recent_errors(limit: int = 20) -> list[dict]:
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM collector_errors ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


# -------------------------------------------------------------------- stats

def get_db_stats() -> dict:
    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        stats = {}
        for table in ("ticks", "macro", "alerts", "collector_errors"):
            stats[f"{table}_count"] = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        oldest = c.execute("SELECT MIN(ts) FROM ticks").fetchone()[0]
        newest = c.execute("SELECT MAX(ts) FROM ticks").fetchone()[0]
        stats["ticks_oldest"] = oldest
        stats["ticks_newest"] = newest
        conn.close()
        return stats


init_monitor_db()
