import os
import time
import logging
import requests
from dotenv import load_dotenv
from .base import BrokerBase, Quote, Position, Order

load_dotenv(override=True)
logger = logging.getLogger(__name__)

BASE_URL = "https://api.invertironline.com"
MERCADO = "bCBA"  # Bolsa de Comercio de Buenos Aires


class IOLBroker(BrokerBase):

    def __init__(self):
        self._token: str = ""
        self._refresh_token: str = ""
        self._token_expiry: float = 0
        self._session = requests.Session()

    # ------------------------------------------------------------------ auth

    def authenticate(self) -> bool:
        user = os.getenv("IOL_USER")
        password = os.getenv("IOL_PASS")
        if not user or not password:
            raise ValueError("IOL_USER y IOL_PASS deben estar en .env")

        resp = self._session.post(
            f"{BASE_URL}/token",
            data={
                "username": user,
                "password": password,
                "grant_type": "password",
            },
        )
        if resp.status_code != 200:
            logger.error(f"IOL auth error {resp.status_code}: {resp.text}")
            return False

        data = resp.json()
        self._token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        self._token_expiry = time.time() + data.get("expires_in", 1800) - 60
        self._session.headers.update({"Authorization": f"Bearer {self._token}"})
        logger.info("IOL autenticado OK")
        return True

    def _ensure_auth(self):
        """
        Garantiza que hay un token válido antes de cada llamada.
        - Si no hay token (primera llamada / restart) → autentica directo.
        - Si el token expiró → intenta refresh; si falla → re-autentica.
        """
        if not self._token:
            # Primera llamada: no hay refresh token todavía, ir directo a password grant
            self.authenticate()
        elif time.time() >= self._token_expiry:
            self._refresh()

    def _refresh(self):
        resp = self._session.post(
            f"{BASE_URL}/token",
            data={
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            logger.warning("Refresh falló, re-autenticando...")
            self.authenticate()
            return
        data = resp.json()
        self._token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        self._token_expiry = time.time() + data.get("expires_in", 1800) - 60
        self._session.headers.update({"Authorization": f"Bearer {self._token}"})

    def _get(self, url: str, **kwargs) -> requests.Response:
        """
        GET con retry automático en 401: re-autentica y reintenta una vez.
        Evita que tokens expirados mid-request corten el ciclo.
        """
        resp = self._session.get(url, **kwargs)
        if resp.status_code == 401:
            logger.warning(f"401 en GET {url} — re-autenticando y reintentando...")
            self.authenticate()
            resp = self._session.get(url, **kwargs)
        return resp

    # ------------------------------------------------------------------ datos

    def get_balance(self) -> dict:
        self._ensure_auth()
        resp = self._get(f"{BASE_URL}/api/v2/estadocuenta")
        resp.raise_for_status()
        data = resp.json()
        # IOL devuelve cuentas con tipo: inversion_Argentina_Pesos, inversion_Argentina_Dolares, etc.
        ars = usd = 0.0
        ars_total = usd_total = 0.0
        ars_titulos = usd_titulos = 0.0
        for cuenta in data.get("cuentas", []):
            tipo = cuenta.get("tipo", "").lower()
            if "pesos" in tipo or tipo == "peso_argentino":
                ars = cuenta.get("disponible", 0)
                ars_total = cuenta.get("total", 0)
                ars_titulos = cuenta.get("titulosValorizados", 0)
            elif "dolar" in tipo and "estados" not in tipo:
                usd = cuenta.get("disponible", 0)
                usd_total = cuenta.get("total", 0)
                usd_titulos = cuenta.get("titulosValorizados", 0)
        return {
            "ars": ars,
            "usd": usd,
            "ars_total": ars_total,
            "usd_total": usd_total,
            "ars_invertido": ars_titulos,
            "usd_invertido": usd_titulos,
        }

    def get_positions(self) -> list[Position]:
        self._ensure_auth()
        resp = self._get(f"{BASE_URL}/api/v2/portafolio/argentina")  # {pais}, no {mercado}
        resp.raise_for_status()
        data = resp.json()
        positions = []
        for item in data.get("activos", []):
            titulo = item.get("titulo", {})
            symbol = titulo.get("simbolo", "")
            qty = item.get("cantidad", 0)
            avg = item.get("ppc", 0)           # precio promedio de compra
            last = item.get("ultimoPrecio", avg)
            if qty > 0:
                positions.append(Position(
                    symbol=symbol,
                    quantity=qty,
                    avg_cost=avg,
                    current_price=last,
                ))
        return positions

    def get_quote(self, symbol: str) -> Quote:
        self._ensure_auth()
        # CotizacionDetalle tiene bid/ask reales en las puntas
        resp = self._get(
            f"{BASE_URL}/api/v2/{MERCADO}/Titulos/{symbol}/CotizacionDetalle"
        )
        if resp.status_code != 200:
            # fallback a cotización simple
            resp = self._get(
                f"{BASE_URL}/api/v2/{MERCADO}/Titulos/{symbol}/Cotizacion"
            )
        resp.raise_for_status()
        d = resp.json()
        puntas = d.get("puntas") or []
        bid = puntas[0].get("precioCompra", 0) if puntas else 0
        ask = puntas[0].get("precioVenta", 0) if puntas else 0
        # IOL devuelve "ultimoPrecio" (no "ultimo")
        last = d.get("ultimoPrecio", d.get("ultimo", 0))
        vol = d.get("volumenNominal", d.get("volumen", 0))
        if last == 0:
            logger.warning(f"[{symbol}] IOL devolvió precio 0 — respuesta: {list(d.keys())}")
        return Quote(
            symbol=symbol,
            last=last,
            bid=bid,
            ask=ask,
            volume=vol,
        )

    def get_serie_historica(
        self,
        symbol: str,
        fecha_desde: str,   # formato: "2023-01-01"
        fecha_hasta: str,   # formato: "2025-01-01"
        ajustada: str = "ajustada",  # "ajustada" | "sinAjustar"
    ) -> list[dict]:
        """Serie histórica directa de IOL — más precisa que yfinance para acciones argentinas."""
        self._ensure_auth()
        resp = self._get(
            f"{BASE_URL}/api/v2/{MERCADO}/Titulos/{symbol}/Cotizacion"
            f"/seriehistorica/{fecha_desde}/{fecha_hasta}/{ajustada}"
        )
        resp.raise_for_status()
        return resp.json()

    def get_mep_rate(self, simbolo: str = "AL30") -> float:
        """Tipo de cambio MEP (dólar financiero). Retorna directamente un number/double según Swagger."""
        self._ensure_auth()
        resp = self._get(f"{BASE_URL}/api/v2/Cotizaciones/MEP/{simbolo}")
        if resp.status_code != 200:
            return 0.0
        try:
            return float(resp.json())   # el endpoint retorna number directamente, no un objeto
        except (ValueError, TypeError):
            return 0.0

    def get_operaciones(self) -> list[dict]:
        """Lista de operaciones del día."""
        self._ensure_auth()
        resp = self._get(f"{BASE_URL}/api/v2/operaciones")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ órdenes

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "limit",
        plazo: str = "t2",
        validez: str = None,
    ) -> Order:
        self._ensure_auth()

        endpoint = "Comprar" if side == "buy" else "Vender"
        tipo_orden = "precioLimite" if order_type == "limit" else "precioMercado"

        # validez: API requiere datetime string. Default = hoy 23:59 (valida para el dia)
        if validez is None:
            from datetime import datetime
            validez = datetime.now().strftime("%Y-%m-%dT23:59:00")

        payload = {
            "mercado": MERCADO,
            "simbolo": symbol,
            "cantidad": quantity,
            "precio": price,
            "plazo": plazo,
            "validez": validez,
            "tipoOrden": tipo_orden,
        }

        resp = self._session.post(
            f"{BASE_URL}/api/v2/operar/{endpoint}",
            json=payload,
        )
        resp.raise_for_status()

        # ResponseModel: {ok: bool, messages: [{codigo, descripcion}]}
        data = resp.json()
        ok = data.get("ok", False)
        messages = data.get("messages", [])

        if not ok:
            msg = "; ".join(m.get("descripcion", "") for m in messages)
            logger.error(f"IOL orden rechazada: {msg}")
            raise RuntimeError(f"Orden rechazada por IOL: {msg}")

        # El número de operación viene en el primer mensaje cuando ok=True
        order_id = str(messages[0].get("codigo", "")) if messages else ""
        logger.info(f"Orden {side.upper()} {symbol} x{quantity} @ {price} → ID {order_id}")

        return Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            status="pending",
        )

    # ------------------------------------------------------------------ FCI

    def get_fci_list(self) -> list[dict]:
        """Lista todos los FCI disponibles."""
        self._ensure_auth()
        resp = self._get(f"{BASE_URL}/api/v2/Titulos/FCI")
        resp.raise_for_status()
        return resp.json() if isinstance(resp.json(), list) else []

    def get_fci_detail(self, simbolo: str) -> dict:
        """Detalle de un FCI por simbolo."""
        self._ensure_auth()
        resp = self._get(f"{BASE_URL}/api/v2/Titulos/FCI/{simbolo}")
        resp.raise_for_status()
        return resp.json()

    def get_fci_types(self) -> list:
        """Lista tipos de fondos FCI."""
        self._ensure_auth()
        resp = self._get(f"{BASE_URL}/api/v2/Titulos/FCI/TipoFondos")
        resp.raise_for_status()
        return resp.json()

    def get_fci_admins(self) -> list:
        """Lista administradoras de FCI."""
        self._ensure_auth()
        resp = self._get(f"{BASE_URL}/api/v2/Titulos/FCI/Administradoras")
        resp.raise_for_status()
        return resp.json()

    def suscribir_fci(self, simbolo: str, monto: float) -> dict:
        """Suscribe (compra) cuotapartes de FCI."""
        self._ensure_auth()
        # Payload inferido — no documentado oficialmente
        resp = self._session.post(
            f"{BASE_URL}/api/v2/operar/suscripcion/fci",
            json={"simbolo": simbolo, "monto": monto},
        )
        return resp.json()

    def rescatar_fci(self, simbolo: str, monto: float) -> dict:
        """Rescata (vende) cuotapartes de FCI."""
        self._ensure_auth()
        resp = self._session.post(
            f"{BASE_URL}/api/v2/operar/rescate/fci",
            json={"simbolo": simbolo, "monto": monto},
        )
        return resp.json()

    def get_caucion_rates(self) -> list[dict]:
        """Tasas de caucion vigentes (solo lectura, no se puede operar via API)."""
        self._ensure_auth()
        resp = self._get(f"{BASE_URL}/api/v2/Cotizaciones/cauciones/argentina/Todos")
        if resp.status_code != 200:
            return []
        return resp.json() if isinstance(resp.json(), list) else []

    def get_instruments(self) -> list:
        """Lista instrumentos cotizables en Argentina."""
        self._ensure_auth()
        resp = self._get(f"{BASE_URL}/api/v2/argentina/Titulos/Cotizacion/Instrumentos")
        if resp.status_code != 200:
            return []
        return resp.json()

    # ------------------------------------------------------------------ órdenes

    def cancel_order(self, order_id: str) -> bool:
        self._ensure_auth()
        resp = self._session.delete(
            f"{BASE_URL}/api/v2/operaciones/{order_id}"
        )
        ok = resp.status_code in (200, 204)
        logger.info(f"Cancelar orden {order_id}: {'OK' if ok else 'FAIL'}")
        return ok

    def get_order_status(self, order_id: str) -> Order:
        self._ensure_auth()
        resp = self._get(
            f"{BASE_URL}/api/v2/operaciones/{order_id}"
        )
        resp.raise_for_status()
        d = resp.json()

        # Estados según Swagger: iniciada | en_Proceso | parcialmente_Terminada | terminada | cancelada
        estado_map = {
            "terminada": "filled",
            "iniciada": "pending",
            "en_Proceso": "pending",
            "parcialmente_Terminada": "partial",
            "cancelada": "cancelled",
        }
        estado = estado_map.get(d.get("estado", ""), "pending")

        return Order(
            order_id=order_id,
            symbol=d.get("simbolo", ""),
            side="buy" if d.get("tipo") == "Compra" else "sell",
            quantity=d.get("cantidad", 0),
            price=d.get("precio", 0),
            status=estado,
        )
