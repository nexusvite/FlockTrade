"""
Support/Resistance Detection Engine for FlockTrade.

Ported from MQL5 V28 EA. Detects S/R levels across M5, M15, M30, H1
timeframes using swing highs/lows, previous-day levels, and round numbers.
Merges confluent levels across timeframes into combined-strength zones.

Strength scoring:
    M5  swing highs/lows : 1
    M15 swing highs/lows : 2
    M30 swing highs/lows : 3
    H1  swing highs/lows : 4
    Previous Day H/L/C   : 5
    Round numbers R20     : 1
    Round numbers R50     : 2
    Round numbers R100    : 3
    Round numbers R1000   : 4

Confluence: levels within MERGE_PIPS of each other are merged, strength summed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from typing import Sequence

logger = logging.getLogger("trading.sr_engine")


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------


@dataclass
class SRLevelData:
    """
    A single detected support/resistance level.

    This is the engine's working object. Separate from the ORM model
    so the engine can be used without a database connection (backtesting).
    """

    price: float
    strength: int
    timeframes: list[str] = field(default_factory=list)
    touches: int = 0
    last_touch: datetime | None = None
    direction: str = "both"   # "support", "resistance", or "both"

    def __post_init__(self) -> None:
        if self.last_touch is None:
            self.last_touch = datetime.now(dt_timezone.utc)

    def merge_with(self, other: "SRLevelData") -> None:
        """
        Absorb another level into this one.

        Combines strength, deduplicated timeframe list, and keeps
        the most recent last_touch.
        """
        self.strength += other.strength
        for tf in other.timeframes:
            if tf not in self.timeframes:
                self.timeframes.append(tf)
        if other.last_touch and (
            self.last_touch is None or other.last_touch > self.last_touch
        ):
            self.last_touch = other.last_touch
        self.touches += other.touches


# ---------------------------------------------------------------------------
# Candle container (mirrors mt5_connector.Candle but avoids a circular import)
# ---------------------------------------------------------------------------


@dataclass
class OHLCBar:
    """Minimal OHLCV bar representation used internally by the engine."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


# ---------------------------------------------------------------------------
# Engine configuration constants
# ---------------------------------------------------------------------------

# Timeframe weight map — matches the strength rules in the PRD
TIMEFRAME_STRENGTH: dict[str, int] = {
    "M5": 1,
    "M15": 2,
    "M30": 3,
    "H1": 4,
}

# Number of pips within which two levels are considered confluent.
# Override this per instrument by passing pip_size to detect_levels().
DEFAULT_MERGE_PIPS = 5

# Minimum bars on each side of a swing point
SWING_LEFT_BARS = 3
SWING_RIGHT_BARS = 3

# Round number levels checked (in quote-currency units)
ROUND_LEVELS = [
    (1000.0, 4),
    (100.0, 3),
    (50.0, 2),
    (20.0, 1),
]


# ---------------------------------------------------------------------------
# Main engine class
# ---------------------------------------------------------------------------


class SREngine:
    """
    Multi-timeframe Support/Resistance detection engine.

    Typical usage inside the scanner loop:

        from trading.sr_engine import SREngine, OHLCBar

        engine = SREngine()
        candles_by_tf = {
            "M5": [...],
            "M15": [...],
            "M30": [...],
            "H1": [...],
        }
        levels = engine.detect_levels(
            symbol="USDJPYm",
            candles_by_tf=candles_by_tf,
            current_price=155.432,
            pip_size=0.01,
        )
    """

    def detect_levels(
        self,
        symbol: str,
        candles_by_tf: dict[str, list[OHLCBar]],
        current_price: float,
        pip_size: float = 0.0001,
    ) -> list[SRLevelData]:
        """
        Main entry point. Returns merged S/R levels sorted by strength desc.

        Args:
            symbol:         Trading symbol, used for logging only.
            candles_by_tf:  Dict mapping timeframe str → list of OHLCBar.
            current_price:  Current market price (bid mid-point).
            pip_size:       One pip in price units (0.0001 for 4-digit pairs,
                            0.01 for JPY pairs, 0.1 for gold in pips).

        Returns:
            Sorted list of SRLevelData, strongest levels first.
        """
        all_levels: list[SRLevelData] = []

        # 1. Swing highs/lows per timeframe
        for tf, candles in candles_by_tf.items():
            if tf not in TIMEFRAME_STRENGTH:
                continue
            swing_levels = self.detect_swing_highs_lows(candles, tf)
            all_levels.extend(swing_levels)
            logger.debug(
                "%s %s: detected %d swing levels", symbol, tf, len(swing_levels)
            )

        # 2. Previous Day H/L/C
        daily_candles = candles_by_tf.get("D1") or candles_by_tf.get("H1") or []
        pd_levels = self.detect_pd_levels(daily_candles)
        all_levels.extend(pd_levels)
        logger.debug("%s PD levels: %d", symbol, len(pd_levels))

        # 3. Round numbers
        round_levels = self.detect_round_numbers(current_price, pip_size)
        all_levels.extend(round_levels)
        logger.debug("%s round levels: %d", symbol, len(round_levels))

        # 4. Merge confluent levels
        merge_distance = DEFAULT_MERGE_PIPS * pip_size
        merged = self.merge_confluent_levels(all_levels, merge_distance)

        # 5. Tag direction relative to current price
        for level in merged:
            if current_price > level.price:
                level.direction = "support"
            elif current_price < level.price:
                level.direction = "resistance"
            else:
                level.direction = "both"

        # Sort by strength descending
        merged.sort(key=lambda lv: lv.strength, reverse=True)
        logger.info("%s: %d merged S/R levels detected", symbol, len(merged))
        return merged

    def detect_swing_highs_lows(
        self,
        candles: list[OHLCBar],
        timeframe: str,
    ) -> list[SRLevelData]:
        """
        Detect swing highs and lows in a candle series.

        A swing high is a bar whose high is greater than the highs of the
        SWING_LEFT_BARS bars before it and SWING_RIGHT_BARS bars after it.
        Swing lows use the inverse logic on bar lows.

        Args:
            candles:    List of OHLCBar, oldest first.
            timeframe:  Timeframe string, e.g. "M15".

        Returns:
            List of SRLevelData with strength set by TIMEFRAME_STRENGTH.
        """
        strength = TIMEFRAME_STRENGTH.get(timeframe, 1)
        n = len(candles)
        levels: list[SRLevelData] = []

        # Need at least left+right+1 bars
        min_bars = SWING_LEFT_BARS + SWING_RIGHT_BARS + 1
        if n < min_bars:
            logger.debug(
                "Skipping swing detection for %s: only %d bars (need %d)",
                timeframe, n, min_bars,
            )
            return levels

        # We skip the most recent SWING_RIGHT_BARS bars because they haven't
        # had enough right-hand confirmation bars yet.
        for i in range(SWING_LEFT_BARS, n - SWING_RIGHT_BARS):
            bar = candles[i]

            # Swing high check
            left_highs = [candles[j].high for j in range(i - SWING_LEFT_BARS, i)]
            right_highs = [candles[j].high for j in range(i + 1, i + SWING_RIGHT_BARS + 1)]

            if bar.high > max(left_highs) and bar.high > max(right_highs):
                levels.append(
                    SRLevelData(
                        price=bar.high,
                        strength=strength,
                        timeframes=[timeframe],
                        last_touch=bar.time,
                        direction="resistance",
                    )
                )

            # Swing low check
            left_lows = [candles[j].low for j in range(i - SWING_LEFT_BARS, i)]
            right_lows = [candles[j].low for j in range(i + 1, i + SWING_RIGHT_BARS + 1)]

            if bar.low < min(left_lows) and bar.low < min(right_lows):
                levels.append(
                    SRLevelData(
                        price=bar.low,
                        strength=strength,
                        timeframes=[timeframe],
                        last_touch=bar.time,
                        direction="support",
                    )
                )

        return levels

    def detect_pd_levels(
        self,
        daily_candles: list[OHLCBar],
    ) -> list[SRLevelData]:
        """
        Detect Previous Day High, Low, and Close from daily candles.

        Requires at least 2 complete daily bars (today's forming bar +
        at least one closed bar).

        Args:
            daily_candles:  List of D1 (or H1 aggregated) bars, oldest first.

        Returns:
            Up to 3 SRLevelData with strength=5 each.
        """
        levels: list[SRLevelData] = []

        if len(daily_candles) < 2:
            return levels

        # The second-to-last bar is the most recently *closed* daily bar.
        # daily_candles[-1] is today's still-forming bar.
        prev_day = daily_candles[-2]

        levels.append(
            SRLevelData(
                price=prev_day.high,
                strength=5,
                timeframes=["PD-H"],
                last_touch=prev_day.time,
                direction="resistance",
            )
        )
        levels.append(
            SRLevelData(
                price=prev_day.low,
                strength=5,
                timeframes=["PD-L"],
                last_touch=prev_day.time,
                direction="support",
            )
        )
        levels.append(
            SRLevelData(
                price=prev_day.close,
                strength=5,
                timeframes=["PD-C"],
                last_touch=prev_day.time,
                direction="both",
            )
        )
        return levels

    def detect_round_numbers(
        self,
        current_price: float,
        pip_size: float = 0.0001,
        look_around: int = 200,
    ) -> list[SRLevelData]:
        """
        Find nearby round-number price levels.

        Searches LOOK_AROUND pips above and below current_price for
        levels at multiples of R20, R50, R100, R1000.

        Args:
            current_price:  Current market price.
            pip_size:       One pip in price units.
            look_around:    How many pips in each direction to search.

        Returns:
            List of SRLevelData with appropriate round-number strength.
        """
        levels: list[SRLevelData] = []
        search_distance = look_around * pip_size

        for round_step, strength in ROUND_LEVELS:
            # Scale: round_step is in "pips * 10" for JPY, price for 4-digit.
            # We express round_step as a raw price increment here.
            step_in_price = round_step * pip_size

            # Find the nearest multiple of step_in_price above and below
            lower_bound = current_price - search_distance
            upper_bound = current_price + search_distance

            # Enumerate multiples within range
            import math
            first_multiple = math.ceil(lower_bound / step_in_price) * step_in_price

            candidate = first_multiple
            while candidate <= upper_bound:
                levels.append(
                    SRLevelData(
                        price=round(candidate, 6),
                        strength=strength,
                        timeframes=[f"R{int(round_step)}"],
                        direction="both",
                    )
                )
                candidate += step_in_price

        return levels

    def merge_confluent_levels(
        self,
        levels: list[SRLevelData],
        merge_distance: float,
    ) -> list[SRLevelData]:
        """
        Merge levels that are within `merge_distance` of each other.

        Uses a single-pass greedy algorithm: sorts levels by price, then
        walks through merging any level that falls within merge_distance
        of the current cluster's representative price.

        Example:
            PD-H at 155.000 (str 5) + H1 swing at 155.002 (str 4) →
            single level at 155.000 with str 9, timeframes ["PD-H","H1"]

        Args:
            levels:         All detected levels (any order).
            merge_distance: Maximum price gap to merge (in raw price units).

        Returns:
            Deduplicated, merged level list.
        """
        if not levels:
            return []

        # Sort by price ascending for efficient single-pass merging
        sorted_levels = sorted(levels, key=lambda lv: lv.price)

        merged: list[SRLevelData] = []
        current_cluster: SRLevelData | None = None

        for level in sorted_levels:
            if current_cluster is None:
                current_cluster = SRLevelData(
                    price=level.price,
                    strength=level.strength,
                    timeframes=list(level.timeframes),
                    touches=level.touches,
                    last_touch=level.last_touch,
                    direction=level.direction,
                )
            elif abs(level.price - current_cluster.price) <= merge_distance:
                # Within merge range — absorb into current cluster
                current_cluster.merge_with(level)
                # Keep the stronger direction if they differ
                if level.direction != current_cluster.direction:
                    current_cluster.direction = "both"
            else:
                merged.append(current_cluster)
                current_cluster = SRLevelData(
                    price=level.price,
                    strength=level.strength,
                    timeframes=list(level.timeframes),
                    touches=level.touches,
                    last_touch=level.last_touch,
                    direction=level.direction,
                )

        if current_cluster is not None:
            merged.append(current_cluster)

        return merged

    def find_nearest_levels(
        self,
        levels: list[SRLevelData],
        current_price: float,
        max_levels: int = 5,
        max_distance_pips: float = 50,
        pip_size: float = 0.0001,
    ) -> list[SRLevelData]:
        """
        Return the `max_levels` levels closest to current_price.

        Filters out levels beyond max_distance_pips.

        Args:
            levels:             Full detected level list.
            current_price:      Current market price.
            max_levels:         Maximum number of levels to return.
            max_distance_pips:  Discard levels further than this.
            pip_size:           One pip in price units.

        Returns:
            Sorted by distance from current_price (nearest first).
        """
        max_distance = max_distance_pips * pip_size

        nearby = [
            lv for lv in levels
            if abs(lv.price - current_price) <= max_distance
        ]

        nearby.sort(key=lambda lv: abs(lv.price - current_price))
        return nearby[:max_levels]
