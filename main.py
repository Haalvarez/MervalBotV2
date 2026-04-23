import os
import time
import threading
from datetime import datetime, timedelta
import pytz
from strategy import Strategy
from strategies.adr_spread import ADRSpreadStrategy
from strategies.ci_t2_arb import CIT2ArbStrategy
from trades import open_trade, close_trade, get_open_trades, log_signal

try:
    from broker import IOLBroker
except ImportError:
    IOLBroker = None

try:
    from telegram import send_signal, send_exit, send_daily_summary
except ImportError:
    def send_signal(*a, **kw): pass
    def send_exit(*a, **kw): pass
    def send_daily_summary(*a, **kw): pass

TZ = pytz.timezone("America/Argentina/Buenos_Aires")

TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"
IOL_USER = os.getenv("IOL_USER")
IOL_PASS = os.getenv("IOL_PASS")

STRATEGIES = [
    ADRSpreadStrategy(),
    CIT2ArbStrategy(),
]

BROKER = None
if not TEST_MODE and IOL_USER and IOL_PASS and IOLBroker:
    BROKER = IOLBroker()

def get_balance():
    # Dummy for now, replace with real broker call
    return {"ars": 1_000_000, "usd": 0}

def main_loop():
    last_daily_summary = None
    while True:
        now = datetime.now(TZ)
        weekday = now.weekday()
        hour = now.hour
        minute = now.minute
        # 1. 10:30 ART → señales pre-open (ADR)
        if hour == 10 and minute >= 30 and minute < 59:
            for strat in STRATEGIES:
                if strat.id == "adr_spread":
                    signals = strat.signals(BROKER)
                    for sig in signals:
                        log_signal(sig, executed=False)
        # 2. 11:00-17:00 → cada 5 minutos: check exits, check Estrategia B
        if hour >= 11 and hour < 17:
            if minute % 5 == 0:
                balance = get_balance() if TEST_MODE else BROKER.get_balance()
                for strat in STRATEGIES:
                    signals = strat.signals(BROKER)
                    open_trades = get_open_trades(strat.id)
                    for sig in signals:
                        should_exec, reason = strat.should_execute(sig, balance, open_trades)
                        if should_exec:
                            qty = int(balance["ars"] // sig.entry_price)
                            if qty > 0:
                                trade_id = open_trade(sig, qty)
                                log_signal(sig, executed=True)
                                send_signal(sig, qty, trade_id)
                        else:
                            log_signal(sig, executed=False)
                # Check exits (SL/TP)
                for trade in get_open_trades():
                    quote = BROKER.get_quote(trade["symbol"]) if BROKER else None
                    price = quote.last if quote else trade["entry_price"]
                    if price <= trade["sl_price"] or price >= trade["tp_price"]:
                        pnl = close_trade(trade["id"], price, "SL/TP hit")
                        send_exit(trade, pnl)
        # 3. 14:30 → cerrar todas las posiciones del día
        if hour == 14 and minute == 30:
            for trade in get_open_trades():
                quote = BROKER.get_quote(trade["symbol"]) if BROKER else None
                price = quote.last if quote else trade["entry_price"]
                pnl = close_trade(trade["id"], price, "Forced exit 14:30")
                send_exit(trade, pnl)
        # 4. 17:00 → resumen diario por Telegram
        if hour == 17 and (not last_daily_summary or last_daily_summary.date() != now.date()):
            send_daily_summary()
            last_daily_summary = now
        time.sleep(30)

if __name__ == "__main__":
    main_loop()
