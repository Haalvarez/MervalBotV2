import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from urllib.parse import urlparse, parse_qs
from strategy import Strategy
from strategies.adr_spread import ADRSpreadStrategy
from strategies.ci_t2_arb import CIT2ArbStrategy
from trades import get_open_trades, get_stats
from datetime import datetime
from activity_log import log_action, RECENT_ACTIONS
from main import main_loop
try:
    from main import BROKER
except ImportError:
    BROKER = None

try:
    from telegram import send_signal
except ImportError:
    def send_signal(*args, **kwargs):
        return None

STRATEGIES = [
    ADRSpreadStrategy(),
    CIT2ArbStrategy(),
]

PORT = int(os.getenv("PORT", 8765))
MAX_ACTIONS = 200
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))
_LAST_ALERT_TS = {}

def send_critical_alert(reason):
    now = time.time()
    last_ts = _LAST_ALERT_TS.get(reason, 0)
    if now - last_ts < ALERT_COOLDOWN_SECONDS:
        return
    _LAST_ALERT_TS[reason] = now
    log_action(f"CRITICAL: {reason}")
    try:
        send_signal({
            "strategy_id": "system",
            "symbol": "-",
            "action": "ALERT",
            "entry_price": 0,
            "sl_price": 0,
            "tp_price": 0,
            "reason": reason,
            "confidence": 0,
        }, 0, None)
    except Exception as exc:
        log_action(f"Error enviando alerta Telegram: {exc}")

def get_real_balance():
    if BROKER is None:
        send_critical_alert("Broker no disponible para consultar saldo")
        return {"ars": 0, "usd": 0}
    try:
        raw_balance = BROKER.get_balance() or {}
        ars = float(raw_balance.get("ars", 0) or 0)
        usd = float(raw_balance.get("usd", 0) or 0)
        return {"ars": ars, "usd": usd}
    except Exception as exc:
        send_critical_alert(f"Error crítico consultando saldo: {exc}")
        return {"ars": 0, "usd": 0}

def get_activity_status(balance):
    if balance.get("ars", 0) > 0 or balance.get("usd", 0) > 0:
        return "active"
    if RECENT_ACTIONS and "CRITICAL" in RECENT_ACTIONS[-1]["message"]:
        return "critical"
    return "no_funds"

class Handler(BaseHTTPRequestHandler):
    def _set_headers(self, content_type="application/json"):
        self.send_response(200)
        self.send_header('Content-type', content_type)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/dashboard.html"):
            self._set_headers("text/html")
            with open("dashboard.html", "rb") as f:
                self.wfile.write(f.read())
        elif parsed.path == "/api/state":
            self._set_headers()
            balance = get_real_balance()
            state = {
                "strategies": [],
                "balance": balance,
                "server_time": datetime.utcnow().isoformat(),
                "last_action_ts": RECENT_ACTIONS[-1]["ts"] if RECENT_ACTIONS else None,
                "status": get_activity_status(balance),
                "recent_actions": RECENT_ACTIONS[-MAX_ACTIONS:],
            }
            for strat in STRATEGIES:
                stats = strat.report()
                open_trades = get_open_trades(strat.id)
                last_signal = None  # Could be loaded from signals table
                state["strategies"].append({
                    **stats,
                    "open_trades": len(open_trades),
                    "last_signal": last_signal
                })
            self.wfile.write(json.dumps(state).encode())
        elif parsed.path == "/api/trades":
            self._set_headers()
            qs = parse_qs(parsed.query)
            strategy = qs.get("strategy", [None])[0]
            limit = int(qs.get("limit", [50])[0])
            # Simple: get last N trades for strategy
            import sqlite3
            from trades import DB_PATH
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            if strategy:
                c.execute("SELECT * FROM trades WHERE strategy_id=? ORDER BY id DESC LIMIT ?", (strategy, limit))
            else:
                c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
            rows = [dict(row) for row in c.fetchall()]
            conn.close()
            self.wfile.write(json.dumps(rows).encode())
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    t = threading.Thread(target=main_loop, daemon=True)
    t.start()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Server running on port {PORT}")
    server.serve_forever()
