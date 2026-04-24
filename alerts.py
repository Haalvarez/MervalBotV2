"""
Detector de movimientos y disparador de alertas Telegram.
Lee ticks recientes, compara contra referencias históricas y
dispara alerta si |delta%| supera el umbral configurado.
Throttle por (symbol, kind) para evitar spam.
"""
import os
from datetime import datetime, timedelta
from typing import Optional

import db
from activity_log import log_action

try:
    from telegram import send_movement_alert
except ImportError:
    def send_movement_alert(*a, **kw): return False


# umbrales en porcentaje (no decimal) → 1.5 = 1.5%
PCT_5MIN  = float(os.getenv("ALERT_PCT_5MIN",  "1.5"))
PCT_1HOUR = float(os.getenv("ALERT_PCT_1HOUR", "3.0"))
PCT_DAY   = float(os.getenv("ALERT_PCT_DAY",   "5.0"))

# throttle: no repetir alerta de (symbol, kind) dentro de N segundos
THROTTLE_SEC = int(os.getenv("ALERT_THROTTLE_SEC", "600"))


WINDOWS = [
    ("5m",  timedelta(minutes=5),  PCT_5MIN),
    ("1h",  timedelta(hours=1),    PCT_1HOUR),
    ("day", timedelta(hours=24),   PCT_DAY),
]


def _is_throttled(symbol: str, kind: str) -> bool:
    last = db.last_alert_ts_for(symbol, kind)
    if not last:
        return False
    try:
        age = (datetime.utcnow() - datetime.fromisoformat(last)).total_seconds()
    except Exception:
        return False
    return age < THROTTLE_SEC


def check_symbol(symbol: str) -> list[dict]:
    """
    Para un símbolo, evalúa las 3 ventanas y dispara alerta si corresponde.
    Retorna lista de alertas emitidas en esta pasada (para logging).
    """
    last_tick = db.get_last_tick(symbol)
    if not last_tick or not last_tick.get("last"):
        return []
    current = float(last_tick["last"])
    emitted = []
    for window_label, delta, pct_threshold in WINDOWS:
        kind = f"move_{window_label}"
        if _is_throttled(symbol, kind):
            continue
        since = (datetime.utcnow() - delta).isoformat()
        prev = db.get_price_at_or_before(symbol, since)
        if prev is None or prev == 0:
            continue
        pct = (current - prev) / prev * 100
        if abs(pct) >= pct_threshold:
            message = f"{symbol} {pct:+.2f}% en {window_label} ({prev:.2f}→{current:.2f})"
            alert_id = db.save_alert(symbol=symbol, kind=kind, message=message, sent=False)
            sent_ok = False
            try:
                sent_ok = send_movement_alert(
                    symbol=symbol, window_label=window_label,
                    pct_change=pct, current_price=current, prev_price=prev,
                )
            except Exception as e:
                log_action(f"alerts: telegram falló para {symbol}: {e}")
            if sent_ok:
                db.mark_alert_sent(alert_id)
            emitted.append({"id": alert_id, "symbol": symbol, "kind": kind,
                            "pct": pct, "sent": sent_ok})
            log_action(f"ALERT [{window_label}] {message} (sent={sent_ok})")
    return emitted


def check_all(symbols: list[str]) -> int:
    """Corre check_symbol sobre una lista. Retorna cantidad total de alertas emitidas."""
    total = 0
    for s in symbols:
        try:
            total += len(check_symbol(s))
        except Exception as e:
            log_action(f"alerts: error procesando {s}: {e}")
    return total
