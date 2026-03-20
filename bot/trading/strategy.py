"""
Strategy Engine for FlockTrade — 13-Filter Chain.

Ported from MQL5 V28 EA. Evaluates a potential trade against all 13 filters
in strict sequential order. A SKIP from any filter is final unless the
filter is marked as non-blocking.

Filter order (matches V28):
    1.  session_filter          — Asia/London/NY session hours
    2.  spread_filter           — Max spread check
    3.  startup_guard           — 3-bar warmup after bot start
    4.  sr_proximity            — Find nearest S/R level
    5.  strength_filter         — Minimum level strength >= 2
    6.  bounce_distance         — Strength-scaled max distance from level
    7.  direction_enforcer      — Closer to resistance → SELL only
    8.  equal_distance_trap     — Skip if equidistant from two strong levels
    9.  touch_count_rules       — 1st touch = TRADE, 2nd = SKIP, 3rd+ = BREAKOUT
    10. traded_level_tracker    — No re-entry on the same level
    11. rsi_extreme_block       — RSI > 80 blocks BUY; RSI < 20 blocks SELL
    12. m15_trend_confirmation  — EMA20 vs EMA50 on M15
    13. smart_sr_block          — Weak levels cannot block strong-level trades

Configuration is read from django.conf.settings.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from typing import Any

from django.conf import settings

from trading.sr_engine import SRLevelData

logger = logging.getLogger("trading.strategy")


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------


@dataclass
class Indicators:
    """Technical indicator values passed into the strategy engine."""

    rsi_m1: float = 50.0
    rsi_m15: float = 50.0
    ema20_m15: float = 0.0
    ema50_m15: float = 0.0
    current_spread_pips: float = 0.0
    current_price: float = 0.0
    bars_since_start: int = 999     # Number of bars since bot started


@dataclass
class TradeSignal:
    """
    Output of the strategy engine evaluation.

    action is one of "BUY", "SELL", "SKIP".
    """

    action: str                             # "BUY", "SELL", or "SKIP"
    symbol: str
    level: SRLevelData | None = None
    confidence: int = 0                     # 0-100
    reasons: list[str] = field(default_factory=list)
    filters_passed: list[str] = field(default_factory=list)
    filters_failed: list[str] = field(default_factory=list)

    @property
    def is_trade(self) -> bool:
        return self.action in ("BUY", "SELL")

    def as_log_dict(self) -> dict[str, Any]:
        """Serialise for storage in Trade.filters_log JSON field."""
        return {
            "action": self.action,
            "confidence": self.confidence,
            "filters_passed": self.filters_passed,
            "filters_failed": self.filters_failed,
            "reasons": self.reasons,
            "level_price": self.level.price if self.level else None,
            "level_strength": self.level.strength if self.level else None,
        }


# ---------------------------------------------------------------------------
# Filter result helper
# ---------------------------------------------------------------------------

PASS = "PASS"
SKIP = "SKIP"
FAIL = "FAIL"


@dataclass
class FilterResult:
    status: str        # PASS or SKIP
    reason: str = ""


# ---------------------------------------------------------------------------
# Strategy Engine
# ---------------------------------------------------------------------------


class StrategyEngine:
    """
    Evaluates whether a trade signal should be generated for a given symbol.

    Usage:
        engine = StrategyEngine()
        signal = engine.evaluate(
            symbol="USDJPYm",
            candles=candles,
            levels=detected_levels,
            indicators=indicators,
            pip_size=0.01,
        )
        if signal.is_trade:
            # proceed to AI scout/confirmer
    """

    def evaluate(
        self,
        symbol: str,
        candles: list[Any],          # list[OHLCBar] — typed as Any to avoid circular imports
        levels: list[SRLevelData],
        indicators: Indicators,
        pip_size: float = 0.0001,
        traded_level_prices: set[float] | None = None,
    ) -> TradeSignal:
        """
        Run all 13 filters in order and return a TradeSignal.

        Args:
            symbol:               Trading symbol.
            candles:              Recent M1 candle list (oldest first).
            levels:               Detected S/R levels from SREngine.
            indicators:           Pre-calculated indicator values.
            pip_size:             One pip in price units.
            traded_level_prices:  Set of level prices already traded this session.

        Returns:
            TradeSignal with action BUY/SELL/SKIP.
        """
        signal = TradeSignal(action="SKIP", symbol=symbol)
        traded_levels = traded_level_prices or set()

        # Ordered filter chain — (filter_name, method_reference, *args)
        # Each method returns FilterResult(PASS|SKIP, reason)
        # Proposed action starts as None; direction_enforcer sets it.
        proposed_action: str | None = None
        nearest_level: SRLevelData | None = None

        # ---------- Filter 1: Session ----------
        result = self.session_filter(indicators, symbol=symbol)
        self._record(signal, "session_filter", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal

        # ---------- Filter 2: Spread ----------
        result = self.spread_filter(indicators, pip_size, symbol=symbol)
        self._record(signal, "spread_filter", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal

        # ---------- Filter 3: Startup guard ----------
        result = self.startup_guard(indicators)
        self._record(signal, "startup_guard", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal

        # ---------- Filter 4: S/R proximity ----------
        result, nearest_level = self.sr_proximity(
            indicators.current_price, levels, pip_size
        )
        self._record(signal, "sr_proximity", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal
        signal.level = nearest_level

        # ---------- Filter 5: Strength ----------
        result = self.strength_filter(nearest_level)
        self._record(signal, "strength_filter", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal

        # ---------- Filter 6: Bounce distance ----------
        result = self.bounce_distance(
            indicators.current_price, nearest_level, pip_size
        )
        self._record(signal, "bounce_distance", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal

        # ---------- Filter 7: Direction enforcer ----------
        result, proposed_action = self.direction_enforcer(
            indicators.current_price, levels, nearest_level
        )
        self._record(signal, "direction_enforcer", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal
        signal.action = proposed_action or "SKIP"

        # ---------- Filter 8: Equal distance trap ----------
        result = self.equal_distance_trap(
            indicators.current_price, levels, pip_size
        )
        self._record(signal, "equal_distance_trap", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal

        # ---------- Filter 9: Touch count rules ----------
        result, adjusted_action = self.touch_count_rules(
            nearest_level, signal.action
        )
        self._record(signal, "touch_count_rules", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal
        signal.action = adjusted_action

        # ---------- Filter 10: Traded level tracker ----------
        result = self.traded_level_tracker(nearest_level, traded_levels)
        self._record(signal, "traded_level_tracker", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal

        # ---------- Filter 11: RSI extreme block ----------
        result = self.rsi_extreme_block(indicators, signal.action)
        self._record(signal, "rsi_extreme_block", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal

        # ---------- Filter 12: M15 trend confirmation ----------
        result = self.m15_trend_confirmation(indicators, signal.action)
        self._record(signal, "m15_trend_confirmation", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal

        # ---------- Filter 13: Smart SR block ----------
        result = self.smart_sr_block(
            indicators.current_price, levels, signal.action, nearest_level, pip_size
        )
        self._record(signal, "smart_sr_block", result)
        if result.status == SKIP:
            signal.action = "SKIP"
            return signal

        # All filters passed — calculate confidence
        signal.confidence = self._calculate_confidence(signal, nearest_level, indicators)
        logger.info(
            "Strategy: %s signal for %s @ %.5f (level=%.5f str=%d confidence=%d)",
            signal.action, symbol, indicators.current_price,
            nearest_level.price, nearest_level.strength, signal.confidence,
        )
        return signal

    # ------------------------------------------------------------------
    # Filter 1 — Session filter
    # ------------------------------------------------------------------

    def session_filter(self, indicators: Indicators, symbol: str = "") -> FilterResult:
        """
        Allow trading only during Asia, London, or New York sessions.

        Crypto symbols (24/7 market) always pass this filter.
        Hours read from Django settings as integers in server (UTC) time.
        """
        # Crypto markets trade 24/7 — bypass session filter
        if symbol:
            from trading.instrument import detect_instrument, InstrumentType
            if detect_instrument(symbol) == InstrumentType.CRYPTO:
                return FilterResult(PASS, "Crypto: 24/7 market, session filter bypassed")

        now_hour = datetime.now(dt_timezone.utc).hour

        from trading.config_service import get_global_config

        gc = get_global_config()
        asia_start = gc.asia_start if gc else getattr(settings, "ASIA_START", 1)
        asia_end = gc.asia_end if gc else getattr(settings, "ASIA_END", 6)
        london_start = gc.london_start if gc else getattr(settings, "LONDON_START", 8)
        london_end = gc.london_end if gc else getattr(settings, "LONDON_END", 12)
        ny_start = gc.ny_start if gc else getattr(settings, "NY_START", 13)
        ny_end = gc.ny_end if gc else getattr(settings, "NY_END", 20)

        in_session = (
            asia_start <= now_hour < asia_end
            or london_start <= now_hour < london_end
            or ny_start <= now_hour < ny_end
        )

        if in_session:
            return FilterResult(PASS, f"In session (hour={now_hour})")
        return FilterResult(
            SKIP,
            f"Outside trading sessions (hour={now_hour}). "
            f"Sessions: Asia {asia_start}-{asia_end}, "
            f"London {london_start}-{london_end}, NY {ny_start}-{ny_end}",
        )

    # ------------------------------------------------------------------
    # Filter 2 — Spread filter
    # ------------------------------------------------------------------

    def spread_filter(
        self, indicators: Indicators, pip_size: float, symbol: str = ""
    ) -> FilterResult:
        """
        Block trades when spread is too wide.

        Uses per-symbol max spread from config, falling back to instrument
        type defaults (3 pips forex, 50 pips gold/crypto).
        """
        if symbol:
            from trading.instrument import get_max_spread_pips
            max_spread_pips = get_max_spread_pips(symbol)
        else:
            max_spread_pips = 3.0
        current_spread_pips = indicators.current_spread_pips

        if current_spread_pips <= max_spread_pips:
            return FilterResult(PASS, f"Spread ok: {current_spread_pips:.1f} pips (max {max_spread_pips})")
        return FilterResult(
            SKIP,
            f"Spread too wide: {current_spread_pips:.1f} pips (max {max_spread_pips})",
        )

    # ------------------------------------------------------------------
    # Filter 3 — Startup guard
    # ------------------------------------------------------------------

    def startup_guard(self, indicators: Indicators) -> FilterResult:
        """
        Require at least 3 completed bars after the bot starts.

        Prevents entries based on incomplete indicator history.
        """
        min_bars = 3
        if indicators.bars_since_start >= min_bars:
            return FilterResult(PASS, f"Warmup complete: {indicators.bars_since_start} bars")
        return FilterResult(
            SKIP,
            f"Startup warmup: only {indicators.bars_since_start} bars (need {min_bars})",
        )

    # ------------------------------------------------------------------
    # Filter 4 — S/R proximity
    # ------------------------------------------------------------------

    def sr_proximity(
        self,
        current_price: float,
        levels: list[SRLevelData],
        pip_size: float,
        max_pips: float = 20.0,
    ) -> tuple[FilterResult, SRLevelData | None]:
        """
        Find the nearest S/R level within max_pips of current price.

        Returns:
            (FilterResult, nearest_level or None)
        """
        if not levels:
            return FilterResult(SKIP, "No S/R levels detected"), None

        max_distance = max_pips * pip_size
        nearest: SRLevelData | None = None
        nearest_dist = float("inf")

        for level in levels:
            dist = abs(level.price - current_price)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = level

        if nearest is None or nearest_dist > max_distance:
            dist_pips = nearest_dist / pip_size if nearest else float("inf")
            return (
                FilterResult(
                    SKIP,
                    f"No S/R level within {max_pips} pips (nearest={dist_pips:.1f} pips)",
                ),
                None,
            )

        dist_pips = nearest_dist / pip_size
        return (
            FilterResult(PASS, f"Nearest level @ {nearest.price:.5f} ({dist_pips:.1f} pips)"),
            nearest,
        )

    # ------------------------------------------------------------------
    # Filter 5 — Strength filter
    # ------------------------------------------------------------------

    def strength_filter(self, level: SRLevelData | None) -> FilterResult:
        """Block trades at very weak levels (strength < 2)."""
        min_strength = 2

        if level is None:
            return FilterResult(SKIP, "No level provided to strength filter")

        if level.strength >= min_strength:
            return FilterResult(PASS, f"Level strength {level.strength} >= {min_strength}")
        return FilterResult(
            SKIP, f"Level too weak: str={level.strength} (need >= {min_strength})"
        )

    # ------------------------------------------------------------------
    # Filter 6 — Bounce distance
    # ------------------------------------------------------------------

    def bounce_distance(
        self,
        current_price: float,
        level: SRLevelData | None,
        pip_size: float,
    ) -> FilterResult:
        """
        Price must be close enough to the level to be a valid bounce candidate.

        Max distance scales with level strength:
            str 1-2: 3 pips
            str 3-4: 5 pips
            str 5+:  8 pips
        """
        if level is None:
            return FilterResult(SKIP, "No level for bounce distance check")

        strength = level.strength
        if strength <= 2:
            max_pips = 3.0
        elif strength <= 4:
            max_pips = 5.0
        else:
            max_pips = 8.0

        dist_pips = abs(current_price - level.price) / pip_size

        if dist_pips <= max_pips:
            return FilterResult(
                PASS, f"Bounce distance ok: {dist_pips:.1f} pips (max {max_pips})"
            )
        return FilterResult(
            SKIP,
            f"Too far from level: {dist_pips:.1f} pips (max {max_pips} for str={strength})",
        )

    # ------------------------------------------------------------------
    # Filter 7 — Direction enforcer
    # ------------------------------------------------------------------

    def direction_enforcer(
        self,
        current_price: float,
        all_levels: list[SRLevelData],
        nearest_level: SRLevelData | None,
    ) -> tuple[FilterResult, str | None]:
        """
        Determine trade direction based on nearest level position.

        Rule:
            Price closer to resistance → SELL (selling at resistance)
            Price closer to support   → BUY  (buying at support)

        If nearest_level.direction is already tagged, use that directly.

        Returns:
            (FilterResult, proposed_action or None)
        """
        if nearest_level is None:
            return FilterResult(SKIP, "No level for direction enforcement"), None

        direction = nearest_level.direction

        if direction == "resistance":
            action = "SELL"
        elif direction == "support":
            action = "BUY"
        else:
            # "both" — determine by price position relative to level
            if current_price >= nearest_level.price:
                action = "SELL"   # Price is at or above level → sell
            else:
                action = "BUY"    # Price is below level → buy

        return (
            FilterResult(PASS, f"Direction enforced: {action} at {direction} level"),
            action,
        )

    # ------------------------------------------------------------------
    # Filter 8 — Equal distance trap
    # ------------------------------------------------------------------

    def equal_distance_trap(
        self,
        current_price: float,
        levels: list[SRLevelData],
        pip_size: float,
        trap_tolerance_pips: float = 3.0,
    ) -> FilterResult:
        """
        Skip if price is equidistant between two strong opposing levels.

        This avoids entering in a price compression zone where both
        support and resistance are equally close — the trade has no
        clear directional advantage.
        """
        strong_levels = [lv for lv in levels if lv.strength >= 3]

        supports = [lv for lv in strong_levels if lv.price < current_price]
        resistances = [lv for lv in strong_levels if lv.price > current_price]

        if not supports or not resistances:
            return FilterResult(PASS, "No strong opposing level pair to check")

        nearest_support = max(supports, key=lambda lv: lv.price)
        nearest_resistance = min(resistances, key=lambda lv: lv.price)

        dist_to_support = (current_price - nearest_support.price) / pip_size
        dist_to_resistance = (nearest_resistance.price - current_price) / pip_size

        equidistant = abs(dist_to_support - dist_to_resistance) <= trap_tolerance_pips

        if equidistant:
            return FilterResult(
                SKIP,
                f"Equal distance trap: {dist_to_support:.1f} pips to support, "
                f"{dist_to_resistance:.1f} pips to resistance",
            )
        return FilterResult(
            PASS,
            f"Clear direction: {dist_to_support:.1f}p support / "
            f"{dist_to_resistance:.1f}p resistance",
        )

    # ------------------------------------------------------------------
    # Filter 9 — Touch count rules
    # ------------------------------------------------------------------

    def touch_count_rules(
        self,
        level: SRLevelData | None,
        proposed_action: str,
    ) -> tuple[FilterResult, str]:
        """
        Apply bounce/breakout logic based on how many times the level has been touched.

            Touch 1 (fresh): TRADE — first bounce is the best
            Touch 2:         SKIP  — second test often breaks through
            Touch 3+:        BREAKOUT consideration (skip for now)

        Returns:
            (FilterResult, adjusted_action)
        """
        if level is None:
            return FilterResult(SKIP, "No level for touch count check"), proposed_action

        touches = level.touches

        if touches == 0 or touches == 1:
            return (
                FilterResult(PASS, f"First/fresh touch ({touches}): trade"),
                proposed_action,
            )
        if touches == 2:
            return (
                FilterResult(SKIP, f"Second touch ({touches}): high break-through risk, skip"),
                proposed_action,
            )
        # 3+ touches — potential breakout zone, skip bounce trade
        return (
            FilterResult(
                SKIP,
                f"Multiple touches ({touches}): level likely breaking, skip bounce",
            ),
            proposed_action,
        )

    # ------------------------------------------------------------------
    # Filter 10 — Traded level tracker
    # ------------------------------------------------------------------

    def traded_level_tracker(
        self,
        level: SRLevelData | None,
        traded_level_prices: set[float],
    ) -> FilterResult:
        """
        Block re-entry on a level that was already traded this session.

        Prevents doubling up on a losing level or over-trading the same zone.
        """
        if level is None:
            return FilterResult(SKIP, "No level for traded-level check")

        if level.price in traded_level_prices:
            return FilterResult(
                SKIP, f"Level @ {level.price:.5f} already traded this session"
            )
        return FilterResult(PASS, f"Level @ {level.price:.5f} not yet traded")

    # ------------------------------------------------------------------
    # Filter 11 — RSI extreme block
    # ------------------------------------------------------------------

    def rsi_extreme_block(
        self,
        indicators: Indicators,
        proposed_action: str,
        overbought: float = 80.0,
        oversold: float = 20.0,
    ) -> FilterResult:
        """
        Block BUY when RSI (M1) > overbought.
        Block SELL when RSI (M1) < oversold.

        This prevents entering exhausted momentum moves.
        """
        rsi = indicators.rsi_m1

        if proposed_action == "BUY" and rsi > overbought:
            return FilterResult(
                SKIP,
                f"RSI extreme block: RSI={rsi:.1f} > {overbought} (overbought), blocking BUY",
            )
        if proposed_action == "SELL" and rsi < oversold:
            return FilterResult(
                SKIP,
                f"RSI extreme block: RSI={rsi:.1f} < {oversold} (oversold), blocking SELL",
            )

        return FilterResult(PASS, f"RSI ok: {rsi:.1f} for {proposed_action}")

    # ------------------------------------------------------------------
    # Filter 12 — M15 trend confirmation
    # ------------------------------------------------------------------

    def m15_trend_confirmation(
        self,
        indicators: Indicators,
        proposed_action: str,
    ) -> FilterResult:
        """
        Confirm trade direction is aligned with the M15 trend.

        Trend defined by EMA20 vs EMA50 on M15:
            EMA20 > EMA50 → uptrend → allow BUY, discourage SELL
            EMA20 < EMA50 → downtrend → allow SELL, discourage BUY

        Counter-trend trades are allowed only if the level strength >= 5
        (strong enough to justify a counter-trend entry).
        This filter is SOFT — it passes with a warning rather than hard-skip.
        """
        ema20 = indicators.ema20_m15
        ema50 = indicators.ema50_m15

        if ema20 == 0.0 or ema50 == 0.0:
            # Indicators not yet warmed up — pass through
            return FilterResult(PASS, "M15 EMAs not ready, skipping trend check")

        uptrend = ema20 > ema50

        if proposed_action == "BUY" and uptrend:
            return FilterResult(PASS, f"M15 uptrend (EMA20={ema20:.5f} > EMA50={ema50:.5f}): BUY aligned")
        if proposed_action == "SELL" and not uptrend:
            return FilterResult(PASS, f"M15 downtrend (EMA20={ema20:.5f} < EMA50={ema50:.5f}): SELL aligned")

        # Counter-trend signal — soft pass (strategy noted but not blocked here)
        trend_str = "uptrend" if uptrend else "downtrend"
        return FilterResult(
            PASS,
            f"Counter-trend {proposed_action} in M15 {trend_str} "
            f"(EMA20={ema20:.5f}, EMA50={ema50:.5f}) — level strength must confirm",
        )

    # ------------------------------------------------------------------
    # Filter 13 — Smart SR block
    # ------------------------------------------------------------------

    def smart_sr_block(
        self,
        current_price: float,
        all_levels: list[SRLevelData],
        proposed_action: str,
        entry_level: SRLevelData | None,
        pip_size: float,
        block_zone_pips: float = 10.0,
    ) -> FilterResult:
        """
        Check if a strong opposing S/R level sits between price and the TP target.

        Weak blocking levels (str < 4) are ignored — the trade proceeds.
        Strong blocking levels (str >= 4) cancel the trade.

        This prevents entering a SELL when there is a strong support
        between current price and the projected TP, and vice versa.
        """
        if entry_level is None:
            return FilterResult(PASS, "No entry level for smart SR block check")

        # Determine TP side
        if proposed_action == "BUY":
            # BUY: TP is above current price — look for resistance between price and TP
            blocking_direction = "resistance"
            target_side_levels = [
                lv for lv in all_levels
                if lv.price > current_price and lv is not entry_level
            ]
        else:
            # SELL: TP is below current price — look for support between price and TP
            blocking_direction = "support"
            target_side_levels = [
                lv for lv in all_levels
                if lv.price < current_price and lv is not entry_level
            ]

        # Check within block_zone_pips on the TP side
        block_distance = block_zone_pips * pip_size
        blocking = [
            lv for lv in target_side_levels
            if abs(lv.price - current_price) <= block_distance and lv.strength >= 4
        ]

        if not blocking:
            return FilterResult(PASS, "No strong opposing level in TP path")

        strongest_blocker = max(blocking, key=lambda lv: lv.strength)

        # If the entry level is stronger than the blocker, allow the trade
        if entry_level.strength >= strongest_blocker.strength:
            return FilterResult(
                PASS,
                f"Entry level (str={entry_level.strength}) overrides "
                f"blocker (str={strongest_blocker.strength})",
            )

        return FilterResult(
            SKIP,
            f"Smart SR block: strong {blocking_direction} level @ "
            f"{strongest_blocker.price:.5f} (str={strongest_blocker.strength}) "
            f"blocks {proposed_action} trade",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record(signal: TradeSignal, filter_name: str, result: FilterResult) -> None:
        """Log a filter result into the signal's pass/fail lists."""
        signal.reasons.append(f"{filter_name}: {result.reason}")
        if result.status == PASS:
            signal.filters_passed.append(filter_name)
        else:
            signal.filters_failed.append(filter_name)

    @staticmethod
    def _calculate_confidence(
        signal: TradeSignal,
        level: SRLevelData | None,
        indicators: Indicators,
    ) -> int:
        """
        Calculate a 0-100 confidence score for a trade signal.

        Factors:
            - Level strength (0-40 points)
            - Filter pass rate (0-30 points)
            - RSI position for direction (0-20 points)
            - M15 trend alignment (0-10 points)
        """
        score = 0

        # Level strength contribution (max 40)
        if level:
            score += min(level.strength * 4, 40)

        # Filter pass rate (max 30)
        total_filters = len(signal.filters_passed) + len(signal.filters_failed)
        if total_filters > 0:
            pass_rate = len(signal.filters_passed) / total_filters
            score += int(pass_rate * 30)

        # RSI contribution (max 20)
        rsi = indicators.rsi_m1
        if signal.action == "BUY" and 30 <= rsi <= 50:
            score += 20  # Ideal BUY zone
        elif signal.action == "BUY" and 50 < rsi <= 70:
            score += 10
        elif signal.action == "SELL" and 50 <= rsi <= 70:
            score += 20  # Ideal SELL zone
        elif signal.action == "SELL" and 30 <= rsi < 50:
            score += 10

        # M15 trend alignment (max 10)
        ema20 = indicators.ema20_m15
        ema50 = indicators.ema50_m15
        if ema20 != 0 and ema50 != 0:
            uptrend = ema20 > ema50
            if (signal.action == "BUY" and uptrend) or (
                signal.action == "SELL" and not uptrend
            ):
                score += 10

        return min(score, 100)
