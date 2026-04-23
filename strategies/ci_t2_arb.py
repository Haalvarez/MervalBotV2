"""
Verificación inicial:
El endpoint IOL /api/v2/bCBA/Titulos/{symbol}/Cotizacion?plazo=t0 fue probado manualmente.
Resultado: (documentar aquí el resultado real tras la prueba en Postman)
- Si devuelve precios distintos para t0 y t2, implementar lógica.
- Si NO diferencia, dejar stub y documentar.
"""

from strategy import Strategy, Signal
from typing import List

class CIT2ArbStrategy(Strategy):
    id = "ci_t2_arb"
    name = "CI/t+2 Arbitrage"
    mode = "paper"

    def signals(self, broker) -> List[Signal]:
        # TODO: implementar si endpoint funciona. Si no, dejar vacío.
        return []

    def should_execute(self, signal: Signal, balance: dict, open_trades: list) -> tuple:
        return False, "Not implemented"

    def report(self) -> dict:
        from trades import get_stats
        stats = get_stats(self.id)
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            **stats
        }
