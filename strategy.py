from dataclasses import dataclass
from typing import Literal

@dataclass
class Signal:
    strategy_id: str
    symbol: str
    action: Literal["BUY", "HOLD", "EXIT"]
    entry_price: float
    sl_price: float
    tp_price: float
    reason: str
    confidence: float      # 0-1, calculado matemáticamente
    plazo: str = "t2"      # t0 | t2

class Strategy:
    id: str
    name: str
    mode: Literal["paper", "live"] = "paper"

    def signals(self, broker) -> list[Signal]:
        raise NotImplementedError

    def should_execute(self, signal: Signal, balance: dict, open_trades: list) -> tuple[bool, str]:
        raise NotImplementedError

    def report(self) -> dict:
        # métricas para dashboard: win_rate, pnl, n_trades, etc.
        raise NotImplementedError
