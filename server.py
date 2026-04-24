"""
Server HTTP del monitor. Sirve dashboard.html + API de lectura de la DB.
Arranca el collector en un daemon thread.
"""
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

from activity_log import log_action, RECENT_ACTIONS
from main import main_loop, build_broker
import db

PORT = int(os.getenv("PORT", 8765))
MAX_ACTIONS = 200


def _broker_balance_safe():
    """Intenta leer saldo IOL. No crítico si falla — el monitor sigue sin eso."""
    try:
        broker = build_broker()
        if broker is None:
            return None
        raw = broker.get_balance() or {}
        return {
            "ars": float(raw.get("ars", 0) or 0),
            "usd": float(raw.get("usd", 0) or 0),
        }
    except Exception as e:
        log_action(f"server: balance fetch falló: {e}")
        return None


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, path):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return  # silenciar access logs

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/dashboard.html"):
            return self._html("dashboard.html")

        if path == "/api/snapshot":
            snapshot = db.get_latest_snapshot()
            macro = db.get_latest_macro()
            return self._json({
                "server_time": datetime.utcnow().isoformat(),
                "snapshot": snapshot,
                "macro": macro,
            })

        if path == "/api/history":
            qs = parse_qs(parsed.query)
            symbol = (qs.get("symbol", [""])[0] or "").upper()
            hours = int(qs.get("hours", ["4"])[0])
            if not symbol:
                return self._json({"error": "symbol requerido"}, 400)
            since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            ticks = db.get_ticks_since(symbol, since)
            return self._json({"symbol": symbol, "hours": hours, "ticks": ticks})

        if path == "/api/alerts":
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["20"])[0])
            return self._json({"alerts": db.get_recent_alerts(limit)})

        if path == "/api/errors":
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["20"])[0])
            return self._json({"errors": db.get_recent_errors(limit)})

        if path == "/api/health":
            stats = db.get_db_stats()
            balance = _broker_balance_safe()
            last_tick_ts = stats.get("ticks_newest")
            # Semáforo: verde si hay tick en últimos 5 min, amarillo <30 min, rojo sino
            status = "unknown"
            if last_tick_ts:
                try:
                    last_dt = datetime.fromisoformat(last_tick_ts)
                    age = (datetime.utcnow() - last_dt).total_seconds()
                    if age < 300: status = "green"
                    elif age < 1800: status = "yellow"
                    else: status = "red"
                except Exception:
                    pass
            return self._json({
                "status": status,
                "server_time": datetime.utcnow().isoformat(),
                "last_tick_ts": last_tick_ts,
                "db_stats": stats,
                "broker_ok": balance is not None,
                "balance": balance,
                "recent_actions": RECENT_ACTIONS[-MAX_ACTIONS:],
            })

        self.send_response(404); self.end_headers()


if __name__ == "__main__":
    db.init_monitor_db()
    t = threading.Thread(target=main_loop, daemon=True, name="collector")
    t.start()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Server running on port {PORT}")
    server.serve_forever()
