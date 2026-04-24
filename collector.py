"""
Collector del monitor. Loop que toma snapshots periódicos de:
- Cotizaciones BYMA (vía IOL)
- Cotizaciones NYSE / ADRs (vía yfinance)
- MEP AL30 y GD30 (vía IOL)
- Tasas de caución (vía IOL)
- CCL implícito (AL30 local vs AL30D)

Frecuencia escalonada según ventana (ver should_tick).
Cada fetch está protegido con try/except; errores se loguean a DB y
el loop nunca muere por un fallo transitorio de IOL o yfinance.
"""
import os
import time
from datetime import datetime, timedelta
import pytz

from db import save_tick, save_macro, log_collector_error
from activity_log import log_action

try:
    from alerts import check_all as check_alerts
except ImportError:
    def check_alerts(_symbols): return 0

TZ = pytz.timezone("America/Argentina/Buenos_Aires")

# ------------------------------------------------------------------ config

def _parse_list(env_val: str) -> list[str]:
    return [s.strip().upper() for s in env_val.split(",") if s.strip()]

BYMA_SYMBOLS = _parse_list(os.getenv(
    "WATCHLIST_BYMA", "GGAL,YPFD,PAMP,BMA,AL30,GD30,AL30D,GD30D"
))
NYSE_SYMBOLS = _parse_list(os.getenv(
    "WATCHLIST_NYSE", "GGAL,YPF,PAM,BMA,SPY"
))

FREQ_MARKET_SEC   = int(os.getenv("FREQ_MARKET_SEC", "60"))      # L-V 11-17 ART
FREQ_EXTENDED_SEC = int(os.getenv("FREQ_EXTENDED_SEC", "300"))   # L-V pre/post mercado
FREQ_OVERNIGHT_SEC= int(os.getenv("FREQ_OVERNIGHT_SEC", "1800")) # L-V overnight
FREQ_WEEKEND_SEC  = int(os.getenv("FREQ_WEEKEND_SEC", "3600"))   # sáb-dom

# ------------------------------------------------------------------ windowing

def current_window(now_art: datetime) -> tuple[str, int]:
    """
    Retorna (nombre_ventana, segundos_entre_snapshots).
    - market:    L-V 11:00–17:00 ART (BYMA abierto)
    - extended:  L-V 10:30–11:00 + 17:00–22:00 ART (pre-open BYMA / NYSE abierto)
    - overnight: L-V resto
    - weekend:   sábado y domingo todo el día
    """
    wd = now_art.weekday()  # 0=lunes, 6=domingo
    h = now_art.hour
    m = now_art.minute
    if wd >= 5:
        return ("weekend", FREQ_WEEKEND_SEC)
    if 11 <= h < 17:
        return ("market", FREQ_MARKET_SEC)
    if (h == 10 and m >= 30) or (17 <= h < 22):
        return ("extended", FREQ_EXTENDED_SEC)
    return ("overnight", FREQ_OVERNIGHT_SEC)


# ------------------------------------------------------------------ fetchers

def snapshot_byma(broker) -> int:
    """Toma quote de cada símbolo BYMA. Retorna cantidad exitosa."""
    if broker is None:
        return 0
    ok = 0
    for symbol in BYMA_SYMBOLS:
        try:
            q = broker.get_quote(symbol)
            if q and q.last:
                save_tick(
                    symbol=symbol, source="iol_byma",
                    last=float(q.last),
                    bid=float(q.bid) if q.bid else None,
                    ask=float(q.ask) if q.ask else None,
                    volume=float(q.volume) if q.volume else None,
                )
                ok += 1
            else:
                log_collector_error("iol_byma", symbol, "quote vacía o last=0")
        except Exception as e:
            log_collector_error("iol_byma", symbol, f"{type(e).__name__}: {e}")
    return ok


def snapshot_nyse() -> int:
    """Toma último close de cada símbolo NYSE vía yfinance. Retorna cantidad exitosa."""
    ok = 0
    try:
        import yfinance as yf
    except ImportError:
        log_collector_error("nyse", None, "yfinance no instalado")
        return 0
    for symbol in NYSE_SYMBOLS:
        try:
            data = yf.download(symbol, period="1d", interval="5m",
                               progress=False, auto_adjust=False)
            if data is None or data.empty:
                log_collector_error("nyse", symbol, "yfinance sin datos")
                continue
            # yfinance a veces retorna MultiIndex
            closes = data["Close"]
            if hasattr(closes, "columns"):
                closes = closes.iloc[:, 0]
            closes = closes.dropna()
            if closes.empty:
                continue
            last = float(closes.iloc[-1])
            save_tick(symbol=symbol, source="yfinance_nyse", last=last)
            ok += 1
        except Exception as e:
            log_collector_error("nyse", symbol, f"{type(e).__name__}: {e}")
    return ok


def snapshot_macro(broker) -> bool:
    """Toma MEP AL30, MEP GD30, caución 1d/7d, calcula CCL."""
    if broker is None:
        return False
    mep_al30 = mep_gd30 = ccl_al30 = c1d = c7d = None

    try:
        mep_al30 = float(broker.get_mep_rate("AL30"))
    except Exception as e:
        log_collector_error("macro", "MEP_AL30", f"{type(e).__name__}: {e}")

    try:
        mep_gd30 = float(broker.get_mep_rate("GD30"))
    except Exception as e:
        log_collector_error("macro", "MEP_GD30", f"{type(e).__name__}: {e}")

    try:
        rates = broker.get_caucion_rates() or []
        # Estructura típica: [{plazo: 1, tasa: 45.5}, {plazo: 7, tasa: ...}]
        for r in rates:
            plazo = int(r.get("plazo") or r.get("dias") or 0)
            tasa = r.get("tasa") or r.get("tasaPromedio")
            if tasa is None:
                continue
            tasa = float(tasa)
            if plazo == 1:
                c1d = tasa
            elif plazo == 7:
                c7d = tasa
    except Exception as e:
        log_collector_error("macro", "caucion", f"{type(e).__name__}: {e}")

    # CCL implícito: AL30 local (ARS) / AL30D local (nominado en USD)
    try:
        from db import get_last_tick
        al30 = get_last_tick("AL30")
        al30d = get_last_tick("AL30D")
        if al30 and al30d and al30["last"] and al30d["last"] and al30d["last"] > 0:
            ccl_al30 = al30["last"] / al30d["last"]
    except Exception as e:
        log_collector_error("macro", "CCL", f"{type(e).__name__}: {e}")

    if any(v is not None for v in (mep_al30, mep_gd30, ccl_al30, c1d, c7d)):
        save_macro(mep_al30=mep_al30, mep_gd30=mep_gd30, ccl_al30=ccl_al30,
                   caucion_1d=c1d, caucion_7d=c7d)
        return True
    return False


# ------------------------------------------------------------------ loop

def run_once(broker) -> dict:
    """Una iteración completa del collector. Retorna stats para log."""
    t0 = time.time()
    n_byma = snapshot_byma(broker)
    n_nyse = snapshot_nyse()
    macro_ok = snapshot_macro(broker)
    # Chequear alertas sobre todos los símbolos que tengan datos
    all_symbols = list(set(BYMA_SYMBOLS) | set(NYSE_SYMBOLS))
    n_alerts = check_alerts(all_symbols)
    elapsed = time.time() - t0
    return {
        "byma_ok": n_byma,
        "byma_total": len(BYMA_SYMBOLS),
        "nyse_ok": n_nyse,
        "nyse_total": len(NYSE_SYMBOLS),
        "macro_ok": macro_ok,
        "alerts": n_alerts,
        "elapsed_sec": round(elapsed, 2),
    }


def collector_loop(broker):
    """Loop infinito. Frecuencia adaptativa según ventana."""
    log_action("collector: iniciando loop")
    while True:
        now_art = datetime.now(TZ)
        window, sleep_sec = current_window(now_art)
        try:
            stats = run_once(broker)
            log_action(
                f"collector[{window}] byma={stats['byma_ok']}/{stats['byma_total']} "
                f"nyse={stats['nyse_ok']}/{stats['nyse_total']} "
                f"macro={'ok' if stats['macro_ok'] else 'skip'} "
                f"alerts={stats['alerts']} "
                f"({stats['elapsed_sec']}s)"
            )
        except Exception as e:
            log_collector_error("loop", None, f"{type(e).__name__}: {e}")
            log_action(f"collector[{window}] ERROR: {e}")
        time.sleep(sleep_sec)
