"""
Instrument Detection for FlockTrade.

Auto-detects whether a symbol is a forex pair, gold, oil, or crypto
based on the symbol name. Returns trading parameters (pip size, lot
size, TP/SL pips) appropriate for each instrument type.

All default values are read from Django settings so they can be
overridden via environment variables without code changes.
"""
from __future__ import annotations

import logging
from enum import Enum

from django.conf import settings

logger = logging.getLogger("trading.instrument")


# ---------------------------------------------------------------------------
# Instrument type enum
# ---------------------------------------------------------------------------


class InstrumentType(Enum):
    """Classification of a tradeable instrument."""

    FOREX = "FOREX"
    GOLD = "GOLD"
    OIL = "OIL"
    CRYPTO = "CRYPTO"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Symbol pattern dictionaries
# ---------------------------------------------------------------------------

# Symbols (or substrings) that indicate Gold / XAUUSD
_GOLD_PATTERNS: frozenset[str] = frozenset(
    {"XAUUSD", "XAUUSDT", "GOLD", "XAU"}
)

# Symbols (or substrings) that indicate Oil / Crude
_OIL_PATTERNS: frozenset[str] = frozenset(
    {"XTIUSD", "USOIL", "WTIUSD", "OIL", "CL", "XBRUSD", "UKOIL", "BRENT"}
)

# Common crypto pairs — extend as needed
_CRYPTO_PATTERNS: frozenset[str] = frozenset(
    {"BTC", "ETH", "XRP", "LTC", "ADA", "SOL", "DOGE", "BNB"}
)

# JPY pairs require 3-decimal pip sizing (0.01 instead of 0.0001)
_JPY_PAIRS: frozenset[str] = frozenset(
    {"USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY"}
)


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------


def detect_instrument(symbol: str) -> InstrumentType:
    """
    Detect the InstrumentType from a symbol name.

    Strips broker-specific suffixes (e.g. "m" in "USDJPYm", ".r" in
    "EURUSD.r") before matching. Also detects Binance-style crypto
    symbols (BTCUSDT, ETHUSDT, SOLUSDT, etc.) by USDT/USDC/BUSD suffix.

    Args:
        symbol: Symbol name, e.g. "USDJPYm", "XAUUSDm", "BTCUSDT".

    Returns:
        InstrumentType enum value.
    """
    clean = _clean_symbol(symbol)

    # Gold
    for pattern in _GOLD_PATTERNS:
        if pattern in clean:
            return InstrumentType.GOLD

    # Oil
    for pattern in _OIL_PATTERNS:
        if pattern in clean:
            return InstrumentType.OIL

    # Crypto — detect by USDT/USDC/BUSD suffix (Binance-style pairs)
    if clean.endswith(("USDT", "USDC", "BUSD")):
        return InstrumentType.CRYPTO

    # Crypto — also detect by known base currencies
    for pattern in _CRYPTO_PATTERNS:
        if pattern in clean:
            return InstrumentType.CRYPTO

    # Forex — 3+3 currency pair structure
    # A valid forex pair is 6 characters composed of two 3-letter currency codes
    if len(clean) == 6 and clean.isalpha():
        return InstrumentType.FOREX

    # Fallback — treat anything else that looks like a currency pair as forex
    if len(clean) >= 6 and clean[:6].isalpha():
        return InstrumentType.FOREX

    logger.warning("Could not detect instrument type for symbol '%s'", symbol)
    return InstrumentType.UNKNOWN


def get_pip_size(symbol: str) -> float:
    """
    Return the pip size in price units for a given symbol.

    Pip definitions:
        JPY pairs: 0.01   (price quoted to 3 decimal places)
        Forex:     0.0001 (price quoted to 5 decimal places)
        Gold:      0.1    (price quoted to 2 decimal places; 1 pip = $0.10)
        Oil:       0.01
        Crypto:    1.0    (very rough — crypto pips vary widely)

    Args:
        symbol: MT5 symbol name.

    Returns:
        Pip size as a float.
    """
    clean = _clean_symbol(symbol)
    instrument = detect_instrument(symbol)

    if instrument == InstrumentType.GOLD:
        return 0.1

    if instrument == InstrumentType.OIL:
        return 0.01

    if instrument == InstrumentType.CRYPTO:
        # High-value crypto (BTC, ETH) use 0.01 pip size;
        # lower-priced coins use 0.0001
        _HIGH_VALUE_CRYPTO = {"BTC", "ETH"}
        for hv in _HIGH_VALUE_CRYPTO:
            if hv in clean:
                return 0.01
        return 0.0001

    # Forex — JPY pairs have a different pip size
    if any(jpy in clean for jpy in _JPY_PAIRS):
        return 0.01

    return 0.0001


def get_lot_size(symbol: str) -> float:
    """
    Return the configured lot size for a symbol.

    Checks: SymbolConfig (per-symbol) → TradingConfig (global) → settings.py.
    """
    from trading.config_service import get_lot_size as _db_lot_size

    return _db_lot_size(symbol)


def get_tp_pips(symbol: str) -> int:
    """
    Return the take-profit distance in pips for a symbol.

    Checks: SymbolConfig (per-symbol) → TradingConfig (global) → settings.py.
    """
    from trading.config_service import get_tp_pips as _db_tp_pips

    return _db_tp_pips(symbol)


def get_sl_pips(symbol: str) -> int:
    """
    Return the stop-loss distance in pips for a symbol.

    Checks: SymbolConfig (per-symbol) → TradingConfig (global) → settings.py.
    """
    from trading.config_service import get_sl_pips as _db_sl_pips

    return _db_sl_pips(symbol)


def get_sl_price(symbol: str, entry_price: float, trade_type: str) -> float:
    """
    Calculate the absolute SL price for an entry.

    Args:
        symbol:      MT5 symbol name.
        entry_price: Entry price of the trade.
        trade_type:  "BUY" or "SELL".

    Returns:
        Absolute stop-loss price level.
    """
    pip_size = get_pip_size(symbol)
    sl_pips = get_sl_pips(symbol)
    sl_distance = sl_pips * pip_size

    if trade_type.upper() == "BUY":
        return round(entry_price - sl_distance, 5)
    else:
        return round(entry_price + sl_distance, 5)


def get_tp_price(symbol: str, entry_price: float, trade_type: str) -> float:
    """
    Calculate the absolute TP price for an entry.

    Args:
        symbol:      MT5 symbol name.
        entry_price: Entry price of the trade.
        trade_type:  "BUY" or "SELL".

    Returns:
        Absolute take-profit price level.
    """
    pip_size = get_pip_size(symbol)
    tp_pips = get_tp_pips(symbol)
    tp_distance = tp_pips * pip_size

    if trade_type.upper() == "BUY":
        return round(entry_price + tp_distance, 5)
    else:
        return round(entry_price - tp_distance, 5)


def get_max_spread_pips(symbol: str) -> float:
    """
    Return the maximum acceptable spread in pips for a symbol.

    Checks SymbolConfig first, then falls back to instrument-type defaults.
    """
    from trading.config_service import get_max_spread_pips as _db_spread

    result = _db_spread(symbol)
    if result is not None:
        return result

    # Hardcoded instrument-type defaults if not in DB
    instrument = detect_instrument(symbol)
    if instrument == InstrumentType.GOLD:
        return 30.0
    if instrument == InstrumentType.OIL:
        return 20.0
    if instrument == InstrumentType.CRYPTO:
        return 50.0
    return 3.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean_symbol(symbol: str) -> str:
    """
    Remove common broker suffixes from a symbol name for pattern matching.

    Exness appends 'm' (e.g. "USDJPYm").
    Other brokers may use '#', '.r', '_SB', etc.
    """
    clean = symbol.upper().strip()

    # Known suffixes to strip (longest first to avoid partial stripping)
    suffixes = [".R", "_SB", ".SB", "#", "M"]
    for suffix in suffixes:
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)]
            break

    return clean
