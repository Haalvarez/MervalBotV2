from strategy import Strategy, Signal
from typing import List

# Estrategia A: ADR Spread (pre-open signal)
# Señal: precio_justo - precio_byma_actual / precio_byma_actual
# Si spread > +1.5%  → BUY al abrir BYMA (BYMA barato vs ADR)
# Si spread < -1.5%  → no operar long ese día ese papel
# SL: -1.5% desde entrada. TP: spread / 2 (convergencia parcial)
# Exit forzado: 14:30 ART siempre (evitar última hora)
# Test data se usa si broker=None

TICKERS = [
    {"byma": "GGAL", "adr": "GGAL", "ratio": 10},
    {"byma": "YPFD", "adr": "YPF", "ratio": 1},
    {"byma": "PAMP", "adr": "PAM", "ratio": 25},
    {"byma": "BMA",  "adr": "BMA", "ratio": 10},
]

class ADRSpreadStrategy(Strategy):
    id = "adr_spread"
    name = "ADR Spread"
    mode = "paper"

    def signals(self, broker) -> List[Signal]:
        import yfinance as yf
        ADR_TICKERS = {"GGAL": "GGAL", "YPFD": "YPF", "PAMP": "PAM", "BMA": "BMA"}
        signals = []
        for t in TICKERS:
            symbol = t["byma"]
            ratio = t["ratio"]
            if broker is None:
                precio_adr_usd = 20.0
                mep_rate = 1200.0
                precio_byma_actual = 22000.0
            else:
                ticker_nyse = ADR_TICKERS.get(symbol)
                data = yf.download(ticker_nyse, period="1d", interval="5m", progress=False)
                precio_adr_usd = float(data["Close"].iloc[-1]) if not data.empty else None
                mep_rate = broker.get_mep_rate("GD30")
                precio_byma_actual = broker.get_quote(symbol).last
            if not precio_adr_usd or not precio_byma_actual:
                continue
            precio_justo = precio_adr_usd * mep_rate / ratio
            spread = (precio_justo - precio_byma_actual) / precio_byma_actual
            if spread > 0.015:
                entry_price = precio_byma_actual
                sl_price = entry_price * (1 - 0.015)
                tp_price = entry_price + (precio_justo - entry_price) * 0.5
                signals.append(Signal(
                    strategy_id=self.id,
                    symbol=symbol,
                    action="BUY",
                    entry_price=entry_price,
                    sl_price=sl_price,
                    tp_price=tp_price,
                    reason=f"ADR spread {spread:.2%}",
                    confidence=min(1.0, abs(spread) / 0.03),
                    plazo="t2"
                ))
            else:
                signals.append(Signal(
                    strategy_id=self.id,
                    symbol=symbol,
                    action="HOLD",
                    entry_price=precio_byma_actual,
                    sl_price=0,
                    tp_price=0,
                    reason=f"ADR spread {spread:.2%} < threshold",
                    confidence=0.0,
                    plazo="t2"
                ))
        return signals

    def should_execute(self, signal: Signal, balance: dict, open_trades: list) -> tuple:
        if signal.action != "BUY":
            return False, "No BUY signal"
        if any(t["symbol"] == signal.symbol for t in open_trades):
            return False, "posición ya abierta"
        if balance.get("ars", 0) < signal.entry_price * 1:
            return False, "Insufficient ARS balance"
        return True, "OK"

    def report(self) -> dict:
        from trades import get_stats
        stats = get_stats(self.id)
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            **stats
        }
