import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from urllib.parse import urlparse, parse_qs
from strategy import Strategy
from strategies.adr_spread import ADRSpreadStrategy
from strategies.ci_t2_arb import CIT2ArbStrategy
from trades import get_open_trades, get_stats
from datetime import datetime
from main import main_loop

STRATEGIES = [
    ADRSpreadStrategy(),
    CIT2ArbStrategy(),
]

PORT = int(os.getenv("PORT", 8765))

class Handler(BaseHTTPRequestHandler):
    def _set_headers(self, content_type="application/json"):
        self.send_response(200)
        self.send_header('Content-type', content_type)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._set_headers("text/html")
            with open("dashboard.html", "rb") as f:
                self.wfile.write(f.read())
        elif parsed.path == "/api/state":
            self._set_headers()
            state = {
                "strategies": [],
                "balance": {"ars": 1_000_000, "usd": 0},
                "last_update": datetime.utcnow().isoformat()
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
