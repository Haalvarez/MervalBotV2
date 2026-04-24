from strategy import Strategy, Signal
from typing import List, Optional
from dataclasses import dataclass

COMMISSION_RT = 0.012
SLIPPAGE_BUFFER = 0.005
MIN_EDGE = 0.008
MIN_SPREAD_ENTRY = COMMISSION_RT + SLIPPAGE_BUFFER + MIN_EDGE
SL_PCT = 0.015


@dataclass
class ADRSignalResult:
    should_signal: bool
    spread: float
    precio_justo: float
    entry_price: float
    sl_price: float
    tp_price: float
    net_target: float
    reason: str


def calc_adr_signal(
    adr_usd: float,
    mep: float,
    byma_last: float,
    ratio: int,
    commission_rt: float = COMMISSION_RT,
    slippage_buffer: float = SLIPPAGE_BUFFER,
    min_edge: float = MIN_EDGE,
    sl_pct: float = SL_PCT,
) -> Optional[ADRSignalResult]:
    if adr_usd <= 0 or mep <= 0 or byma_last <= 0 or ratio <= 0:
        return None
    precio_justo = adr_usd * mep / ratio
    spread = (precio_justo - byma_last) / byma_last
    min_spread_entry = commission_rt + slippage_buffer + min_edge
    entry_price = byma_last
    sl_price = entry_price * (1 - sl_pct)
    net_target = max(spread - commission_rt, 0.01)
    tp_price = entry_price * (1 + net_target)
    if spread > min_spread_entry:
        return ADRSignalResult(
            should_signal=True,
            spread=spread,
            precio_justo=precio_justo,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            net_target=net_target,
            reason=f"ADR spread {spread*100:.2f}% > umbral {min_spread_entry*100:.2f}%",
        )
    return ADRSignalResult(
        should_signal=False,
        spread=spread,
        precio_justo=precio_justo,
        entry_price=entry_price,
        sl_price=sl_price,
        tp_price=tp_price,
        net_target=net_target,
        reason=f"spread {spread*100:+.2f}% bajo umbral",
    )


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
        from activity_log import log_action
        ADR_TICKERS = {"GGAL": "GGAL", "YPFD": "YPF", "PAMP": "PAM", "BMA": "BMA"}
        signals = []
        for t in TICKERS:
            symbol = t["byma"]
            ratio = t["ratio"]
            if broker is None:
                adr_usd = 20.0
                mep = 1200.0
                byma_last = 22000.0
            else:
                ticker_nyse = ADR_TICKERS.get(symbol)
                data = yf.download(ticker_nyse, period="1d", interval="5m", progress=False)
                closes = data["Close"].dropna().tail(3)
                if len(closes) < 2:
                    log_action(f"[adr_spread] {symbol}: ADR sin datos suficientes, skip")
                    continue
                adr_usd = float(closes.mean())
                mep = broker.get_mep_rate("GD30")
                quote = broker.get_quote(symbol)
                byma_last = quote.last if quote and quote.last else None
                if byma_last is None or byma_last <= 0:
                    log_action(f"[adr_spread] {symbol}: sin precio BYMA válido, skip")
                    continue
            result = calc_adr_signal(adr_usd, mep, byma_last, ratio)
            if result is None:
                log_action(f"[adr_spread] {symbol}: datos inválidos, skip")
                continue
            log_action(
                f"[adr_spread] {symbol}: ADR=${adr_usd:.2f} "
                f"MEP=${mep:.2f} ratio={ratio} "
                f"justo=${result.precio_justo:.2f} actual=${byma_last:.2f} "
                f"spread={result.spread*100:+.2f}% "
                f"umbral={MIN_SPREAD_ENTRY:.2%} "
                f"{'→ SEÑAL BUY' if result.should_signal else '→ sin señal'} "
                f"{result.reason}"
            )
            if result.should_signal:
                signals.append(Signal(
                    strategy_id=self.id,
                    symbol=symbol,
                    action="BUY",
                    entry_price=result.entry_price,
                    sl_price=result.sl_price,
                    tp_price=result.tp_price,
                    reason=result.reason,
                    confidence=1.0,
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
