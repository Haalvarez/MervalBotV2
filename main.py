"""
mervalBotV2 — Monitor mode.

El viejo loop de trading (estrategias, señales, trades) fue retirado.
Ahora este proceso es un collector de datos de mercado:
- Snapshots periódicos de cotizaciones BYMA (IOL) y NYSE (yfinance)
- MEP, CCL y tasas de caución
- Alertas Telegram por movimientos configurables
- Todo persistido en SQLite para análisis offline

Pivot driven por backtest: estrategia ADR-spread no tiene edge estadística.
Monitor primero → datos propios → backtests honestos después.
"""
import os
from collector import collector_loop
from activity_log import log_action

try:
    from broker import IOLBroker
except ImportError:
    IOLBroker = None

try:
    from telegram import send_startup
except ImportError:
    def send_startup(*a, **kw): pass


def build_broker():
    """Broker IOL solo si hay credenciales. Sin credenciales, el collector
    solo captura NYSE (yfinance). No es un error."""
    if IOLBroker is None:
        log_action("main: IOLBroker no disponible (import falló)")
        return None
    user = os.getenv("IOL_USER")
    pw = os.getenv("IOL_PASS")
    if not user or not pw:
        log_action("main: IOL_USER/IOL_PASS no definidos — collector sin BYMA")
        return None
    try:
        b = IOLBroker()
        # authenticate() se llama lazy en el primer request
        return b
    except Exception as e:
        log_action(f"main: error creando IOLBroker: {e}")
        return None


def main_loop():
    """Punto de entrada. Llamado por server.py en un daemon thread."""
    log_action("=" * 50)
    log_action("mervalBotV2 — monitor mode iniciando")
    try:
        send_startup()
    except Exception as e:
        log_action(f"main: send_startup falló: {e}")
    broker = build_broker()
    log_action(f"main: broker={'OK' if broker else 'None'}")
    collector_loop(broker)


if __name__ == "__main__":
    main_loop()
