import os
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

def send_signal(signal, qty, trade_id):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    msg = f"[SIGNAL] {signal.strategy_id} {signal.symbol} {signal.action}\nQty: {qty} @ {signal.entry_price:.2f}\nSL: {signal.sl_price:.2f} TP: {signal.tp_price:.2f}\nReason: {signal.reason}\nTrade ID: {trade_id}"
    requests.post(API_URL, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def send_exit(trade, pnl):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    msg = f"[EXIT] {trade['strategy_id']} {trade['symbol']}\nEntry: {trade['entry_price']:.2f} Close: {trade.get('close_price', 0):.2f}\nPnL: {pnl:.2f} ARS ({trade.get('pnl_pct', 0):.2f}%)\nReason: {trade.get('reason', '')}"
    requests.post(API_URL, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def send_daily_summary():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    msg = "[DAILY SUMMARY] (implementar resumen de trades y métricas)"
    requests.post(API_URL, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
