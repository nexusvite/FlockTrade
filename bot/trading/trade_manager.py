"""
Trade Manager for FlockTrade.

Manages open positions — monitoring exit conditions every minute
and executing closes when criteria are met.

Exit logic (in priority order):
    1. AI-based exit recommendation (HOLD/CLOSE) — checked every minute
    2. Profit protection: lock in at +1.2 pips unrealised profit
    3. Max hold: close after 20 bars regardless of P&L
    4. Touch exit: close if at weak level (str < 4) and price touches TP zone
    5. Daily loss limit: circuit breaker (handled by BotStatus)

The TradeManager does NOT make AI calls itself. The scanner loop
(tasks.py) is responsible for calling the AI engine and passing
the AI recommendation here via manage_open_trade().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.utils import timezone

from trading.sr_engine import SRLevelData

logger = logging.getLogger("trading.trade_manager")


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------


@dataclass
class ActiveTrade:
    """
    In-memory representation of a currently open position.

    Mirrors the data in the Trade ORM model but is designed for fast
    in-process access without repeated DB queries on every tick.
    """

    db_id: str                      # UUID of the Trade ORM record
    ticket: int                     # MT5 position ticket
    symbol: str
    type: str                       # "BUY" or "SELL"
    entry_price: float
    sl: float
    tp: float
    lot_size: float
    entry_level: SRLevelData
    entry_time: datetime = field(default_factory=lambda: datetime.now(dt_timezone.utc))
    bars_open: int = 0
    current_pnl: float = 0.0
    ai_holds: int = 0               # consecutive AI HOLD decisions
    pip_size: float = 0.0001

    @property
    def unrealised_pips(self) -> float:
        """Current unrealised profit in pips (positive = profit)."""
        if self.type == "BUY":
            return (self.current_pnl / self.pip_size) if self.pip_size > 0 else 0.0
        else:
            return (self.current_pnl / self.pip_size) if self.pip_size > 0 else 0.0

    @property
    def is_in_profit(self) -> bool:
        return self.current_pnl > 0


@dataclass
class ExitDecision:
    """Return value of the exit evaluation methods."""

    should_close: bool
    reason: str
    urgency: str = "normal"     # "normal" or "immediate"


# ---------------------------------------------------------------------------
# Trade Manager
# ---------------------------------------------------------------------------


class TradeManager:
    """
    Evaluates exit conditions for open trades and instructs the MT5 connector
    to close positions when warranted.

    Usage (called from tasks.py each minute):

        manager = TradeManager(connector=get_connector())

        for active_trade in active_trades:
            decision = manager.manage_open_trade(
                trade=active_trade,
                current_price=current_price,
                ai_recommendation="HOLD",   # or "CLOSE"
            )
            if decision.should_close:
                manager.execute_close(active_trade, decision.reason)
    """

    # Profit protection threshold in pips
    PROFIT_PROTECTION_PIPS: float = 1.2

    # Maximum bars to hold a trade open
    MAX_HOLD_BARS: int = 20

    # Level strength below which a "touch exit" is applied
    TOUCH_EXIT_STRENGTH_THRESHOLD: int = 4

    # Pips from TP at which we consider price "at TP" for touch exit
    TP_ZONE_PIPS: float = 0.5

    def __init__(self, connector: Any = None) -> None:
        """
        Args:
            connector: An MT5Connector instance. If None, the module-level
                       singleton from mt5_connector.get_connector() is used.
        """
        if connector is None:
            from trading.binance_connector import get_connector
            self._connector = get_connector()
        else:
            self._connector = connector

    def manage_open_trade(
        self,
        trade: ActiveTrade,
        current_price: float,
        ai_recommendation: str = "HOLD",
    ) -> ExitDecision:
        """
        Evaluate all exit conditions for a single open trade.

        Conditions are checked in priority order. Returns the first
        exit trigger found, or ExitDecision(False, "Hold") if none apply.

        Args:
            trade:              The active trade to evaluate.
            current_price:      Latest market price for the symbol.
            ai_recommendation:  "HOLD" or "CLOSE" from the AI exit model.

        Returns:
            ExitDecision indicating whether to close and why.
        """
        # Update in-memory P&L based on current price
        trade.current_pnl = self._calculate_pnl(trade, current_price)
        trade.bars_open += 1

        logger.debug(
            "Managing %s %s ticket=%d bars=%d pnl=%.2f pips ai=%s",
            trade.symbol, trade.type, trade.ticket,
            trade.bars_open, trade.unrealised_pips, ai_recommendation,
        )

        # --- Priority 1: Daily loss limit (circuit breaker) ---
        decision = self._check_daily_loss_limit()
        if decision.should_close:
            return decision

        # --- Priority 2: Profit protection ---
        decision = self._check_profit_protection(trade)
        if decision.should_close:
            return decision

        # --- Priority 3: Max hold bars ---
        decision = self._check_max_hold(trade)
        if decision.should_close:
            return decision

        # --- Priority 4: Touch exit for weak levels ---
        decision = self._check_touch_exit(trade, current_price)
        if decision.should_close:
            return decision

        # --- Priority 5: AI-based exit ---
        decision = self._check_ai_recommendation(trade, ai_recommendation)
        if decision.should_close:
            return decision

        return ExitDecision(should_close=False, reason="Hold — no exit condition triggered")

    def execute_close(
        self,
        trade: ActiveTrade,
        exit_reason: str,
    ) -> bool:
        """
        Close the MT5 position and update the database Trade record.

        Args:
            trade:       The active trade to close.
            exit_reason: Human-readable reason for the exit.

        Returns:
            True if the close succeeded, False otherwise.
        """
        logger.info(
            "Closing %s %s ticket=%d: %s",
            trade.symbol, trade.type, trade.ticket, exit_reason,
        )

        try:
            result = self._connector.close_trade(
                ticket=trade.ticket,
                comment=f"FlockTrade-Exit"[:31],
            )
        except Exception as exc:
            logger.error("MT5 close_trade failed for ticket %d: %s", trade.ticket, exc)
            return False

        if not result.success:
            logger.error(
                "Close rejected for ticket %d: %s (code=%d)",
                trade.ticket, result.error_message, result.error_code,
            )
            return False

        # Update the database record
        self._persist_close(trade, result.price, exit_reason)

        # Update daily stats
        self._update_daily_stats(trade)

        logger.info(
            "Trade closed: %s %s ticket=%d exit=%.5f pnl=%.2f reason=%s",
            trade.symbol, trade.type, trade.ticket,
            result.price, trade.current_pnl, exit_reason,
        )
        return True

    # ------------------------------------------------------------------
    # Exit condition evaluators
    # ------------------------------------------------------------------

    def _check_daily_loss_limit(self) -> ExitDecision:
        """
        Check if the daily circuit breaker has been triggered.

        Reads limits from Django settings; checks BotStatus.
        """
        try:
            from trading.models import BotStatus
            status = BotStatus.objects.get_status()
            if status.is_circuit_breaker_triggered:
                return ExitDecision(
                    should_close=True,
                    reason="Daily loss limit reached — circuit breaker active",
                    urgency="immediate",
                )
        except Exception as exc:
            logger.warning("Could not check daily loss limit: %s", exc)

        return ExitDecision(should_close=False, reason="Daily loss limit ok")

    def _check_profit_protection(self, trade: ActiveTrade) -> ExitDecision:
        """
        Close if trade is in profit >= PROFIT_PROTECTION_PIPS but has started
        to give back gains.

        This implements a basic trailing stop at the +1.2 pip threshold:
        once profit exceeds the threshold, we lock in by closing immediately.
        """
        pips = trade.unrealised_pips

        if pips >= self.PROFIT_PROTECTION_PIPS:
            logger.debug(
                "Profit protection triggered for %s ticket=%d: +%.2f pips",
                trade.symbol, trade.ticket, pips,
            )
            return ExitDecision(
                should_close=True,
                reason=f"Profit protection: +{pips:.2f} pips >= {self.PROFIT_PROTECTION_PIPS}",
            )

        return ExitDecision(should_close=False, reason="Below profit protection threshold")

    def _check_max_hold(self, trade: ActiveTrade) -> ExitDecision:
        """Close if the trade has been open for MAX_HOLD_BARS or more."""
        if trade.bars_open >= self.MAX_HOLD_BARS:
            return ExitDecision(
                should_close=True,
                reason=f"Max hold reached: {trade.bars_open} bars (limit {self.MAX_HOLD_BARS})",
                urgency="immediate",
            )
        return ExitDecision(
            should_close=False,
            reason=f"Hold bar count: {trade.bars_open}/{self.MAX_HOLD_BARS}",
        )

    def _check_touch_exit(
        self, trade: ActiveTrade, current_price: float
    ) -> ExitDecision:
        """
        For weak levels only (str < TOUCH_EXIT_STRENGTH_THRESHOLD):
        close when price reaches the TP zone.

        Strong levels should ride out to the hard TP — we trust the level.
        """
        if trade.entry_level.strength >= self.TOUCH_EXIT_STRENGTH_THRESHOLD:
            return ExitDecision(
                should_close=False,
                reason=(
                    f"Strong level (str={trade.entry_level.strength}): "
                    "trust SL/TP, no touch exit"
                ),
            )

        tp_zone = self.TP_ZONE_PIPS * trade.pip_size

        if trade.type == "BUY" and (current_price >= trade.tp - tp_zone):
            return ExitDecision(
                should_close=True,
                reason=(
                    f"Touch exit BUY: price {current_price:.5f} near TP {trade.tp:.5f} "
                    f"(weak level str={trade.entry_level.strength})"
                ),
            )
        if trade.type == "SELL" and (current_price <= trade.tp + tp_zone):
            return ExitDecision(
                should_close=True,
                reason=(
                    f"Touch exit SELL: price {current_price:.5f} near TP {trade.tp:.5f} "
                    f"(weak level str={trade.entry_level.strength})"
                ),
            )

        return ExitDecision(should_close=False, reason="Not in TP zone")

    def _check_ai_recommendation(
        self, trade: ActiveTrade, recommendation: str
    ) -> ExitDecision:
        """
        Act on the AI exit model's recommendation.

        "CLOSE" → close immediately.
        "HOLD"  → increment hold counter and hold.

        After 15 consecutive AI HOLDs with the trade flat or negative,
        override to close (avoid infinite holds on stagnant trades).
        """
        if recommendation.upper() == "CLOSE":
            return ExitDecision(
                should_close=True,
                reason=f"AI exit model recommended CLOSE",
            )

        trade.ai_holds += 1

        # Anti-stagnation: close if AI keeps holding a losing trade
        max_ai_holds_losing = 15
        if (
            trade.ai_holds >= max_ai_holds_losing
            and not trade.is_in_profit
        ):
            return ExitDecision(
                should_close=True,
                reason=(
                    f"Anti-stagnation: {trade.ai_holds} consecutive AI HOLDs "
                    f"on a losing trade"
                ),
            )

        return ExitDecision(
            should_close=False,
            reason=f"AI HOLD ({trade.ai_holds} consecutive)",
        )

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _persist_close(
        self,
        trade: ActiveTrade,
        exit_price: float,
        exit_reason: str,
    ) -> None:
        """Update the Trade ORM record with exit data."""
        try:
            from trading.models import Trade

            Trade.objects.filter(pk=trade.db_id).update(
                exit_price=Decimal(str(exit_price)),
                exit_time=timezone.now(),
                bars_held=trade.bars_open,
                pnl=Decimal(str(round(trade.current_pnl, 2))),
                exit_reason=exit_reason,
            )
        except Exception as exc:
            logger.error("Failed to persist trade close to DB for %s: %s", trade.db_id, exc)

    def _update_daily_stats(self, trade: ActiveTrade) -> None:
        """Increment today's DailyStats counters after a close."""
        try:
            from trading.models import DailyStats
            from django.db.models import F

            pnl = round(trade.current_pnl, 2)
            stats = DailyStats.get_today()

            stats.trades = F("trades") + 1
            stats.pnl = F("pnl") + Decimal(str(pnl))

            if pnl > 0:
                stats.wins = F("wins") + 1
            elif pnl < 0:
                stats.losses = F("losses") + 1
                # Update daily loss counter on BotStatus
                from trading.models import BotStatus
                bot = BotStatus.objects.get_status()
                bot.daily_losses = F("daily_losses") + 1
                bot.daily_loss_usd = F("daily_loss_usd") + Decimal(str(abs(pnl)))
                bot.save()
            else:
                stats.scratches = F("scratches") + 1

            stats.save()

            # Refresh to get actual values for best/worst tracking
            stats.refresh_from_db()

            if stats.best_trade is None or pnl > float(stats.best_trade):
                DailyStats.objects.filter(date=stats.date).update(
                    best_trade=Decimal(str(pnl))
                )
            if stats.worst_trade is None or pnl < float(stats.worst_trade):
                DailyStats.objects.filter(date=stats.date).update(
                    worst_trade=Decimal(str(pnl))
                )

        except Exception as exc:
            logger.error("Failed to update daily stats: %s", exc)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_pnl(trade: ActiveTrade, current_price: float) -> float:
        """
        Approximate unrealised P&L in USD for a position.

        For a precise figure the MT5 account currency and point value
        must be considered. This is a simplified calculation suitable
        for exit decision logic.
        """
        if trade.type == "BUY":
            pip_diff = (current_price - trade.entry_price) / trade.pip_size
        else:
            pip_diff = (trade.entry_price - current_price) / trade.pip_size

        # Very rough P&L estimate — proper value comes from MT5 position.profit
        return round(pip_diff * trade.lot_size, 2)
