"""Notificaciones Telegram del monitor."""
import os
import requests
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


def _send(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        r = requests.post(
            API_URL,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def send_startup() -> bool:
    text = (
        f"📡 <b>mervalBotV2 monitor iniciado</b>\n"
        f"Hora: {datetime.now().strftime('%Y-%m-%d %H:%M')} ART\n"
        f"Modo: collector (sin trading)"
    )
    return _send(text)


def send_movement_alert(symbol: str, window_label: str, pct_change: float,
                        current_price: float, prev_price: float) -> bool:
    arrow = "🟢" if pct_change > 0 else "🔻"
    text = (
        f"{arrow} <b>{symbol}</b> {pct_change:+.2f}% en {window_label}\n"
        f"Precio: ${prev_price:,.2f} → <b>${current_price:,.2f}</b>"
    )
    return _send(text)


def send_daily_summary(stats: dict) -> bool:
    """stats = {ticks_count, macro_count, alerts_count, errors_count, ...}"""
    lines = [f"📊 <b>Monitor resumen diario</b> {datetime.now().strftime('%Y-%m-%d')}"]
    for k in ("ticks_count", "macro_count", "alerts_count", "collector_errors_count"):
        if k in stats:
            label = k.replace("_count", "").replace("_", " ")
            lines.append(f"• {label}: {stats[k]:,}")
    return _send("\n".join(lines))
