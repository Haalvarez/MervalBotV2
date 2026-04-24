import os
import requests
from trades import get_stats, _get_conn, _lock

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"
STRATEGY_IDS = ["adr_spread", "ci_t2_arb"]

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


def _send(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    requests.post(
        API_URL,
        data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )


def _mode_tag() -> str:
    return "PAPER" if TEST_MODE else "LIVE"


def send_signal(signal, qty, trade_id):
    total_ars = qty * signal.entry_price
    risk_pct = abs(signal.entry_price - signal.sl_price) / signal.entry_price * 100
    gain_pct = abs(signal.tp_price - signal.entry_price) / signal.entry_price * 100
    text = (
        f"🟢 <b>ABRE</b> [{_mode_tag()}] {signal.symbol} {signal.plazo}\n"
        f"Estrategia: {signal.strategy_id}\n"
        f"Compra {qty} @ ${signal.entry_price:,.2f}  (${total_ars:,.0f})\n"
        f"SL ${signal.sl_price:,.2f} (-{risk_pct:.2f}%)  "
        f"TP ${signal.tp_price:,.2f} (+{gain_pct:.2f}%)\n"
        f"Motivo: {signal.reason}\n"
        f"Trade #{trade_id}"
    )
    _send(text)


def send_exit(trade, pnl):
    icon = "✅" if pnl > 0 else "🔻"
    pnl_pct = trade.get("pnl_pct") or 0
    close_price = trade.get("close_price") or 0
    text = (
        f"{icon} <b>CIERRA</b> [{_mode_tag()}] {trade['symbol']}\n"
        f"Estrategia: {trade['strategy_id']}\n"
        f"Entrada ${trade['entry_price']:,.2f}  →  Salida ${close_price:,.2f}\n"
        f"PnL: ${pnl:,.0f} ({pnl_pct:+.2f}%)\n"
        f"Motivo: {trade.get('reason', '')}\n"
        f"Trade #{trade['id']}"
    )
    _send(text)


def send_daily_summary():
    from datetime import datetime
    lines = [f"📊 <b>Resumen diario</b> [{_mode_tag()}] {datetime.now().strftime('%Y-%m-%d')}"]
    total_pnl = 0
    total_trades = 0
    for sid in STRATEGY_IDS:
        s = get_stats(sid)
        total_pnl += s["pnl_ars"]
        total_trades += s["n_trades"]
        lines.append(
            f"• {sid}: {s['n_trades']} trades | win {s['win_rate']*100:.0f}% | "
            f"PnL ${s['pnl_ars']:,.0f}"
        )

    with _lock:
        conn = _get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM trades WHERE date(entry_ts)=date('now','localtime')"
        )
        trades_today = c.fetchone()[0]
        c.execute(
            "SELECT COALESCE(SUM(pnl_ars),0) FROM trades "
            "WHERE status='CLOSED' AND date(close_ts)=date('now','localtime')"
        )
        pnl_today = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
        open_now = c.fetchone()[0]
        conn.close()

    lines.append("")
    lines.append(f"Hoy: {trades_today} trades abiertos | PnL ${pnl_today:,.0f}")
    lines.append(f"Posiciones abiertas ahora: {open_now}")
    lines.append(f"Acumulado histórico: {total_trades} trades | PnL ${total_pnl:,.0f}")
    _send("\n".join(lines))
