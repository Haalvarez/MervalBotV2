from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Quote:
    symbol: str
    last: float
    bid: float
    ask: float
    volume: float


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_cost: float
    current_price: float

    @property
    def pnl_pct(self) -> float:
        return (self.current_price - self.avg_cost) / self.avg_cost * 100


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str       # "buy" | "sell"
    quantity: float
    price: float
    status: str     # "pending" | "filled" | "cancelled" | "partial"


class BrokerBase(ABC):

    @abstractmethod
    def authenticate(self) -> bool:
        """Login / refresh token. Retorna True si OK."""

    @abstractmethod
    def get_balance(self) -> dict:
        """Retorna {'ars': float, 'usd': float}"""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Lista de posiciones abiertas."""

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        """Cotización actual de un símbolo (ej: 'GGAL')."""

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,          # "buy" | "sell"
        quantity: int,
        price: float,
        order_type: str = "limit",   # "limit" | "market"
    ) -> Order:
        """Envía una orden. Retorna Order con order_id."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancela una orden pendiente."""

    @abstractmethod
    def get_order_status(self, order_id: str) -> Order:
        """Estado actual de una orden."""
