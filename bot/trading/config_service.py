"""
Config service: DB-first configuration with Redis caching.

All backend code should read config through these functions instead of
directly from django.conf.settings. Falls back to settings.py if DB
row doesn't exist yet (e.g. before first migration).
"""

import logging
from functools import lru_cache

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

GLOBAL_CACHE_KEY = "trading_config:global"
SYMBOL_CACHE_PREFIX = "trading_config:symbol:"
ACTIVE_SYMBOLS_KEY = "trading_config:active_symbols"
CACHE_TTL = 60  # seconds


def get_global_config():
    """Return the singleton TradingConfig, cached for 60s."""
    cached = cache.get(GLOBAL_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        from trading.models import TradingConfig

        config = TradingConfig.objects.get_config()
        cache.set(GLOBAL_CACHE_KEY, config, CACHE_TTL)
        return config
    except Exception:
        logger.debug("TradingConfig not available, using settings.py fallback")
        return None


def get_symbol_config(symbol: str):
    """Return SymbolConfig for a symbol, or None if not configured."""
    cache_key = f"{SYMBOL_CACHE_PREFIX}{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached != "__none__" else None

    try:
        from trading.models import SymbolConfig

        sc = SymbolConfig.objects.filter(symbol=symbol).first()
        cache.set(cache_key, sc if sc else "__none__", CACHE_TTL)
        return sc
    except Exception:
        return None


def get_active_symbols() -> list[str]:
    """Return list of enabled symbols from DB, fallback to settings.SYMBOLS."""
    cached = cache.get(ACTIVE_SYMBOLS_KEY)
    if cached is not None:
        return cached

    try:
        from trading.models import SymbolConfig

        symbols = list(
            SymbolConfig.objects.filter(enabled=True)
            .values_list("symbol", flat=True)
        )
        if symbols:
            cache.set(ACTIVE_SYMBOLS_KEY, symbols, CACHE_TTL)
            return symbols
    except Exception:
        pass

    return getattr(settings, "SYMBOLS", [])


def invalidate_config_cache():
    """Bust all config caches after a write."""
    cache.delete(GLOBAL_CACHE_KEY)
    cache.delete(ACTIVE_SYMBOLS_KEY)
    # Symbol-specific keys are invalidated by TTL expiry or explicit delete
    try:
        from trading.models import SymbolConfig

        for symbol in SymbolConfig.objects.values_list("symbol", flat=True):
            cache.delete(f"{SYMBOL_CACHE_PREFIX}{symbol}")
    except Exception:
        pass


# --- Convenience getters with DB → settings.py fallback ---


def get_lot_size(symbol: str) -> float:
    """Per-symbol lot size → global instrument default → settings.py."""
    sc = get_symbol_config(symbol)
    if sc and sc.lot_size is not None:
        return float(sc.lot_size)

    gc = get_global_config()
    from trading.instrument import detect_instrument, InstrumentType

    itype = detect_instrument(symbol)
    if gc:
        if itype == InstrumentType.GOLD:
            return float(gc.lot_size_gold)
        if itype == InstrumentType.CRYPTO:
            # Crypto default: use lot_size_forex as fallback (or 0.01)
            return float(getattr(settings, "LOT_SIZE_CRYPTO", 0.01))
        return float(gc.lot_size_forex)

    if itype == InstrumentType.GOLD:
        return float(getattr(settings, "LOT_SIZE_GOLD", 0.1))
    if itype == InstrumentType.CRYPTO:
        return float(getattr(settings, "LOT_SIZE_CRYPTO", 0.01))
    return float(getattr(settings, "LOT_SIZE_FOREX", 1.0))


def get_tp_pips(symbol: str) -> int:
    sc = get_symbol_config(symbol)
    if sc and sc.tp_pips is not None:
        return sc.tp_pips

    gc = get_global_config()
    from trading.instrument import detect_instrument, InstrumentType

    itype = detect_instrument(symbol)
    if gc:
        if itype == InstrumentType.GOLD:
            return gc.tp_pips_gold
        return gc.tp_pips_forex

    if itype == InstrumentType.GOLD:
        return int(getattr(settings, "TP_PIPS_GOLD", 20))
    return int(getattr(settings, "TP_PIPS_FOREX", 2))


def get_sl_pips(symbol: str) -> int:
    sc = get_symbol_config(symbol)
    if sc and sc.sl_pips is not None:
        return sc.sl_pips

    gc = get_global_config()
    from trading.instrument import detect_instrument, InstrumentType

    itype = detect_instrument(symbol)
    if gc:
        if itype == InstrumentType.GOLD:
            return gc.sl_pips_gold
        return gc.sl_pips_forex

    if itype == InstrumentType.GOLD:
        return int(getattr(settings, "SL_PIPS_GOLD", 50))
    return int(getattr(settings, "SL_PIPS_FOREX", 5))


def get_max_spread_pips(symbol: str) -> float | None:
    sc = get_symbol_config(symbol)
    if sc and sc.max_spread_pips is not None:
        return float(sc.max_spread_pips)
    return None
