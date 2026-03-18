"""
Technical Indicators for FlockTrade.

Pure-function implementations of RSI and EMA using numpy.
No Django dependencies — safe to import in backtesting contexts.

All functions accept a plain list or numpy array of float close prices
and return a float (most recent value) or numpy array depending on the variant.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger("trading.indicators")


# ---------------------------------------------------------------------------
# RSI — Relative Strength Index
# ---------------------------------------------------------------------------


def calculate_rsi(closes: list[float] | np.ndarray, period: int = 14) -> float:
    """
    Calculate the RSI for the most recent bar.

    Implements Wilder's smoothing (identical to MetaTrader's iRSI).

    Args:
        closes: Price series, oldest value first. Must have at least
                period + 1 elements for a valid result.
        period: Lookback period (default: 14).

    Returns:
        RSI value 0-100 for the last element in the series.
        Returns 50.0 if there is insufficient data.

    Example:
        rsi = calculate_rsi(closes=m1_closes, period=14)
    """
    arr = np.asarray(closes, dtype=np.float64)

    if len(arr) < period + 1:
        logger.debug("RSI: insufficient data (%d bars, need %d)", len(arr), period + 1)
        return 50.0

    # Price changes
    deltas = np.diff(arr)

    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Initial simple average over the first `period` changes
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    # Wilder smoothing for remaining bars
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0.0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def calculate_rsi_series(
    closes: list[float] | np.ndarray, period: int = 14
) -> np.ndarray:
    """
    Calculate RSI for every bar in the series (vectorised).

    Returns an array of the same length as `closes`. The first `period`
    values are filled with 50.0 (insufficient data).

    Args:
        closes: Price series, oldest value first.
        period: Lookback period.

    Returns:
        numpy array of RSI values.
    """
    arr = np.asarray(closes, dtype=np.float64)
    n = len(arr)
    rsi_values = np.full(n, 50.0)

    if n < period + 1:
        return rsi_values

    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Seed values from first period
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    # First valid RSI at index `period`
    if avg_loss == 0.0:
        rsi_values[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi_values[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        idx = i + 1   # +1 because deltas is one shorter than closes
        if avg_loss == 0.0:
            rsi_values[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_values[idx] = round(100.0 - (100.0 / (1.0 + rs)), 2)

    return rsi_values


# ---------------------------------------------------------------------------
# EMA — Exponential Moving Average
# ---------------------------------------------------------------------------


def calculate_ema(closes: list[float] | np.ndarray, period: int) -> float:
    """
    Calculate the EMA for the most recent bar.

    Uses the standard multiplier k = 2 / (period + 1), seeded with a
    simple moving average over the first `period` bars.

    Args:
        closes: Price series, oldest value first. Must have at least
                `period` elements.
        period: EMA period.

    Returns:
        EMA value for the last element in the series.
        Returns the last close value if data is insufficient.

    Example:
        ema20 = calculate_ema(closes=m15_closes, period=20)
        ema50 = calculate_ema(closes=m15_closes, period=50)
    """
    arr = np.asarray(closes, dtype=np.float64)

    if len(arr) < period:
        logger.debug("EMA(%d): insufficient data (%d bars)", period, len(arr))
        return float(arr[-1]) if len(arr) > 0 else 0.0

    k = 2.0 / (period + 1)
    ema = float(np.mean(arr[:period]))   # seed with SMA

    for price in arr[period:]:
        ema = price * k + ema * (1.0 - k)

    return round(ema, 6)


def calculate_ema_series(
    closes: list[float] | np.ndarray, period: int
) -> np.ndarray:
    """
    Calculate EMA for every bar in the series.

    Returns an array of the same length as `closes`. The first `period - 1`
    values are filled with NaN (insufficient data).

    Args:
        closes: Price series, oldest value first.
        period: EMA period.

    Returns:
        numpy array of EMA values.
    """
    arr = np.asarray(closes, dtype=np.float64)
    n = len(arr)
    ema_values = np.full(n, np.nan)

    if n < period:
        return ema_values

    k = 2.0 / (period + 1)

    # Seed with SMA
    ema = float(np.mean(arr[:period]))
    ema_values[period - 1] = ema

    for i in range(period, n):
        ema = arr[i] * k + ema * (1.0 - k)
        ema_values[i] = round(ema, 6)

    return ema_values


# ---------------------------------------------------------------------------
# SMA — Simple Moving Average (utility)
# ---------------------------------------------------------------------------


def calculate_sma(closes: list[float] | np.ndarray, period: int) -> float:
    """
    Calculate the simple moving average of the last `period` bars.

    Args:
        closes: Price series, oldest value first.
        period: Lookback period.

    Returns:
        SMA value. Returns last close if insufficient data.
    """
    arr = np.asarray(closes, dtype=np.float64)

    if len(arr) < period:
        return float(arr[-1]) if len(arr) > 0 else 0.0

    return round(float(np.mean(arr[-period:])), 6)


# ---------------------------------------------------------------------------
# ATR — Average True Range (useful for dynamic SL sizing)
# ---------------------------------------------------------------------------


def calculate_atr(
    highs: list[float] | np.ndarray,
    lows: list[float] | np.ndarray,
    closes: list[float] | np.ndarray,
    period: int = 14,
) -> float:
    """
    Calculate ATR using Wilder's smoothing method.

    Args:
        highs:  High prices, oldest first.
        lows:   Low prices, oldest first.
        closes: Close prices, oldest first.
        period: ATR period (default: 14).

    Returns:
        ATR value for the most recent bar.
        Returns 0.0 if insufficient data.
    """
    h = np.asarray(highs, dtype=np.float64)
    l = np.asarray(lows, dtype=np.float64)
    c = np.asarray(closes, dtype=np.float64)

    n = min(len(h), len(l), len(c))
    if n < period + 1:
        return 0.0

    h, l, c = h[:n], l[:n], c[:n]

    # True range for each bar
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(
            np.abs(h[1:] - c[:-1]),
            np.abs(l[1:] - c[:-1]),
        ),
    )

    if len(tr) < period:
        return 0.0

    # Seed with SMA of first period
    atr = float(np.mean(tr[:period]))

    # Wilder smooth
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period

    return round(atr, 6)
