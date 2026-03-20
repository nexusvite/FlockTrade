"""
Celery Tasks for FlockTrade.

Three periodic tasks scheduled via CELERY_BEAT_SCHEDULE in settings.py:

    run_scanner()    — Main 1-minute trading loop. Scans all symbols,
                       runs S/R detection, applies the 13-filter strategy,
                       calls the AI engine, and opens trades.

    monitor_exits()  — Checks all open positions for exit conditions
                       every minute using the TradeManager.

    health_check()   — Verifies MT5 connectivity every 30 seconds and
                       updates BotStatus accordingly.

Each task is idempotent and designed to handle partial failures gracefully
(log the error, update BotStatus, and return without crashing the worker).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone
from typing import Any

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("trading.tasks")


# ---------------------------------------------------------------------------
# Main scanner task
# ---------------------------------------------------------------------------


@shared_task(
    name="trading.tasks.run_scanner",
    bind=True,
    max_retries=0,           # Never auto-retry — next beat will run it again
    ignore_result=True,
    time_limit=55,           # Kill task after 55s (beat fires every 60s)
    soft_time_limit=45,      # Raise SoftTimeLimitExceeded at 45s for clean exit
)
def run_scanner(self: Any) -> None:
    """
    Main 1-minute scanner loop.

    For each configured symbol:
        1. Fetch candles from MT5 for M5/M15/M30/H1 timeframes
        2. Calculate indicators (RSI, EMA)
        3. Run SREngine to detect S/R levels
        4. Run StrategyEngine 13-filter chain
        5. If signal is BUY/SELL: call AI Scout
        6. If Scout recommends BUY/SELL: call AI Confirmer
        7. If Confirmer confirms: open the trade

    Skips all symbols if:
        - BotStatus.is_paused is True
        - BotStatus.is_circuit_breaker_triggered is True
        - MT5 is disconnected
    """
    from trading.models import BotStatus, Trade, SRLevel as SRLevelModel
    from trading.binance_connector import get_connector, ConnectorError
    from trading.sr_engine import SREngine, OHLCBar
    from trading.strategy import StrategyEngine, Indicators
    from trading.indicators import calculate_rsi, calculate_ema
    from trading.instrument import (
        detect_instrument, get_pip_size, get_lot_size,
        get_tp_price, get_sl_price, get_max_spread_pips,
    )

    for account_type in ("DEMO", "REAL"):
        try:
            _run_scanner_for_account(account_type)
        except Exception as exc:
            logger.error(
                "Scanner: unhandled error for %s account: %s",
                account_type, exc, exc_info=True,
            )


def _run_scanner_for_account(account_type: str) -> None:
    """Run the scanner loop for a single account type."""
    from trading.models import BotStatus, Trade, SRLevel as SRLevelModel
    from trading.binance_connector import get_connector, ConnectorError
    from trading.sr_engine import SREngine, OHLCBar
    from trading.strategy import StrategyEngine, Indicators
    from trading.indicators import calculate_rsi, calculate_ema
    from trading.instrument import (
        detect_instrument, get_pip_size, get_lot_size,
        get_tp_price, get_sl_price, get_max_spread_pips,
    )

    bot_status = BotStatus.objects.get_status(account_type)

    # --- Guard checks ---
    if bot_status.is_paused:
        logger.info("Scanner [%s]: bot is paused, skipping scan", account_type)
        return

    if bot_status.is_circuit_breaker_triggered:
        logger.warning("Scanner [%s]: circuit breaker active, skipping scan", account_type)
        return

    connector = get_connector(account_type)
    if not connector.ensure_connected():
        logger.error("Scanner [%s]: exchange not connected, skipping scan", account_type)
        bot_status.mark_disconnected(f"Scanner: exchange unreachable [{account_type}]")
        return

    # Update last scan time
    BotStatus.objects.filter(account_type=account_type).update(
        last_scan_time=timezone.now(),
        is_running=True,
    )

    from trading.config_service import get_active_symbols

    symbols: list[str] = get_active_symbols()
    sr_engine = SREngine()
    strategy_engine = StrategyEngine()

    # Track which level prices have been traded this session (in-memory)
    traded_level_prices: set[float] = set(
        SRLevelModel.objects.filter(traded=True).values_list("price", flat=True)
    )

    for symbol in symbols:
        try:
            _scan_symbol(
                symbol=symbol,
                connector=connector,
                sr_engine=sr_engine,
                strategy_engine=strategy_engine,
                traded_level_prices=traded_level_prices,
                account_type=account_type,
            )
        except Exception as exc:
            logger.error("Scanner [%s]: unhandled error scanning %s: %s", account_type, symbol, exc, exc_info=True)

    logger.debug("Scanner [%s]: completed scan of %d symbols", account_type, len(symbols))


def _scan_symbol(
    symbol: str,
    connector: Any,
    sr_engine: Any,
    strategy_engine: Any,
    traded_level_prices: set[float],
    account_type: str = "DEMO",
) -> None:
    """
    Single-symbol scan logic extracted from run_scanner for clarity.

    Intentionally not a Celery task itself — called synchronously within
    the scanner's time budget.
    """
    from trading.binance_connector import ConnectorError
    from trading.sr_engine import OHLCBar
    from trading.strategy import Indicators
    from trading.indicators import calculate_rsi, calculate_ema
    from trading.instrument import (
        get_pip_size, get_lot_size, get_tp_price, get_sl_price,
        get_max_spread_pips,
    )

    pip_size = get_pip_size(symbol)

    # --- Fetch candles ---
    candles_by_tf: dict[str, list[OHLCBar]] = {}
    for tf, count in [("M5", 100), ("M15", 100), ("M30", 100), ("H1", 100), ("D1", 10)]:
        try:
            raw = connector.get_candles(symbol, tf, count)
            candles_by_tf[tf] = [
                OHLCBar(
                    time=c.time,
                    open=c.open,
                    high=c.high,
                    low=c.low,
                    close=c.close,
                    volume=c.volume,
                )
                for c in raw
            ]
        except ConnectorError as exc:
            logger.warning("Cannot fetch %s %s candles: %s", symbol, tf, exc)
            if tf in ("M5", "M15"):
                # Critical timeframes — skip this symbol
                logger.error("Skipping %s scan — critical timeframe unavailable", symbol)
                return

    # --- Current tick ---
    try:
        tick = connector.get_tick(symbol)
        current_price = (tick.bid + tick.ask) / 2
        spread_pips = tick.spread_points / pip_size
    except ConnectorError as exc:
        logger.warning("Cannot get tick for %s: %s", symbol, exc)
        return

    # --- Calculate indicators ---
    m1_closes = [c.close for c in candles_by_tf.get("M5", [])]
    m15_closes = [c.close for c in candles_by_tf.get("M15", [])]

    rsi_m1 = calculate_rsi(m1_closes, period=14) if m1_closes else 50.0
    rsi_m15 = calculate_rsi(m15_closes, period=14) if m15_closes else 50.0
    ema20_m15 = calculate_ema(m15_closes, period=20) if len(m15_closes) >= 20 else 0.0
    ema50_m15 = calculate_ema(m15_closes, period=50) if len(m15_closes) >= 50 else 0.0

    # Determine bars since start from BotStatus
    from trading.models import BotStatus
    bot_status = BotStatus.objects.get_status(account_type)
    bars_since_start = 999  # Default: warmup complete (status doesn't track per-symbol yet)

    indicators = Indicators(
        rsi_m1=rsi_m1,
        rsi_m15=rsi_m15,
        ema20_m15=ema20_m15,
        ema50_m15=ema50_m15,
        current_spread_pips=spread_pips,
        current_price=current_price,
        bars_since_start=bars_since_start,
    )

    # --- S/R detection ---
    levels = sr_engine.detect_levels(
        symbol=symbol,
        candles_by_tf=candles_by_tf,
        current_price=current_price,
        pip_size=pip_size,
    )

    # Persist/update detected levels in DB
    _persist_sr_levels(symbol, levels)

    # --- Strategy filter chain ---
    signal = strategy_engine.evaluate(
        symbol=symbol,
        candles=candles_by_tf.get("M5", []),
        levels=levels,
        indicators=indicators,
        pip_size=pip_size,
        traded_level_prices=traded_level_prices,
    )

    if not signal.is_trade:
        logger.debug("%s: SKIP — %s", symbol, signal.reasons[-1] if signal.reasons else "")
        return

    logger.info(
        "%s: Strategy signal %s confidence=%d — calling AI Scout",
        symbol, signal.action, signal.confidence,
    )

    # --- AI Scout ---
    scout_result = _call_ai_scout(symbol, signal, indicators, candles_by_tf)
    if not scout_result or scout_result.get("action") not in ("BUY", "SELL"):
        logger.info("%s: Scout SKIP — %s", symbol, scout_result.get("reason", ""))
        return

    logger.info(
        "%s: Scout %s confidence=%d — calling Confirmer",
        symbol, scout_result["action"], scout_result.get("confidence", 0),
    )

    # --- AI Confirmer ---
    confirm_result = _call_ai_confirmer(symbol, signal, scout_result, indicators, candles_by_tf)
    if not confirm_result or confirm_result.get("action") != "CONFIRM":
        logger.info("%s: Confirmer REJECT — %s", symbol, confirm_result.get("reason", ""))
        return

    logger.info(
        "%s: Confirmer CONFIRM confidence=%d — opening trade",
        symbol, confirm_result.get("confidence", 0),
    )

    # --- Open trade ---
    _open_trade(
        symbol=symbol,
        signal=signal,
        scout_result=scout_result,
        confirm_result=confirm_result,
        connector=connector,
        pip_size=pip_size,
        account_type=account_type,
    )


def _persist_sr_levels(symbol: str, levels: list[Any]) -> None:
    """Save detected S/R levels to the database, updating existing entries."""
    from trading.models import SRLevel as SRLevelModel

    # Clear old levels for this symbol before saving fresh ones
    SRLevelModel.objects.filter(symbol=symbol).delete()

    batch = []
    for level in levels:
        batch.append(
            SRLevelModel(
                symbol=symbol,
                price=level.price,
                strength=level.strength,
                timeframes=level.timeframes,
                session_touches=level.touches,
                first_detected=level.last_touch or timezone.now(),
                last_touched=level.last_touch,
                traded=False,
            )
        )
    SRLevelModel.objects.bulk_create(batch, ignore_conflicts=True)


def _call_ai_scout(
    symbol: str,
    signal: Any,
    indicators: Any,
    candles_by_tf: dict[str, list[Any]],
) -> dict[str, Any] | None:
    """
    Call the AI Scout model.

    Delegates to the ai.engine module to keep trading/ clean.
    Returns a dict with keys: action, confidence, reason.
    Returns None on error.
    """
    try:
        from ai.engine import get_ai_engine
        engine = get_ai_engine()

        m1_candles = candles_by_tf.get("M5", [])[-15:]
        context = {
            "symbol": symbol,
            "action": signal.action,
            "level_price": signal.level.price if signal.level else None,
            "level_strength": signal.level.strength if signal.level else None,
            "rsi": indicators.rsi_m1,
            "ema20": indicators.ema20_m15,
            "ema50": indicators.ema50_m15,
            "candles": [
                {"o": c.open, "h": c.high, "l": c.low, "c": c.close}
                for c in m1_candles
            ],
            "filters_passed": signal.filters_passed,
            "confidence": signal.confidence,
        }

        import asyncio
        result = asyncio.run(engine.scout_scan(context))
        return result

    except Exception as exc:
        logger.error("AI Scout call failed for %s: %s", symbol, exc, exc_info=True)
        return None


def _call_ai_confirmer(
    symbol: str,
    signal: Any,
    scout_result: dict[str, Any],
    indicators: Any,
    candles_by_tf: dict[str, list[Any]],
) -> dict[str, Any] | None:
    """
    Call the AI Confirmer model.

    Only called after Scout returns BUY/SELL.
    Returns a dict with keys: action (CONFIRM/REJECT), confidence, reason.
    Returns None on error.
    """
    try:
        from ai.engine import get_ai_engine
        engine = get_ai_engine()

        m1_candles = candles_by_tf.get("M5", [])[-15:]
        m15_candles = candles_by_tf.get("M15", [])[-15:]

        context = {
            "symbol": symbol,
            "proposed_action": signal.action,
            "scout_action": scout_result.get("action"),
            "scout_confidence": scout_result.get("confidence"),
            "scout_reason": scout_result.get("reason"),
            "level_price": signal.level.price if signal.level else None,
            "level_strength": signal.level.strength if signal.level else None,
            "level_timeframes": signal.level.timeframes if signal.level else [],
            "rsi_m1": indicators.rsi_m1,
            "rsi_m15": indicators.rsi_m15,
            "ema20_m15": indicators.ema20_m15,
            "ema50_m15": indicators.ema50_m15,
            "m1_candles": [
                {"o": c.open, "h": c.high, "l": c.low, "c": c.close}
                for c in m1_candles
            ],
            "m15_candles": [
                {"o": c.open, "h": c.high, "l": c.low, "c": c.close}
                for c in m15_candles
            ],
            "filters_passed": signal.filters_passed,
            "filters_failed": signal.filters_failed,
        }

        import asyncio
        result = asyncio.run(engine.confirm_trade(context))
        return result

    except Exception as exc:
        logger.error("AI Confirmer call failed for %s: %s", symbol, exc, exc_info=True)
        return None


def _open_trade(
    symbol: str,
    signal: Any,
    scout_result: dict[str, Any],
    confirm_result: dict[str, Any],
    connector: Any,
    pip_size: float,
    account_type: str = "DEMO",
) -> None:
    """
    Execute a market order and persist the Trade record.
    """
    from trading.instrument import get_lot_size, get_tp_price, get_sl_price
    from trading.models import Trade, SRLevel as SRLevelModel

    lot_size = get_lot_size(symbol)

    try:
        tick = connector.get_tick(symbol)
        entry_price = tick.ask if signal.action == "BUY" else tick.bid
    except Exception as exc:
        logger.error("Cannot get entry tick for %s: %s", symbol, exc)
        return

    sl = get_sl_price(symbol, entry_price, signal.action)
    tp = get_tp_price(symbol, entry_price, signal.action)

    result = connector.open_trade(
        symbol=symbol,
        trade_type=signal.action,
        lot=lot_size,
        sl=sl,
        tp=tp,
        comment="FlockTrade",
    )

    if not result.success:
        logger.error(
            "Trade open failed for %s %s: %s (code=%d)",
            symbol, signal.action, result.error_message, result.error_code,
        )
        return

    # Persist to database
    level = signal.level
    trade = Trade.objects.create(
        symbol=symbol,
        type=signal.action,
        account_type=account_type,
        binance_order_id=str(result.ticket) if result.ticket else "",
        entry_price=result.price,
        sl=sl,
        tp=tp,
        lot_size=lot_size,
        entry_time=timezone.now(),
        level_price=level.price if level else None,
        level_strength=level.strength if level else None,
        level_timeframes=",".join(level.timeframes) if level else "",
        scout_action=scout_result.get("action", ""),
        scout_confidence=scout_result.get("confidence"),
        scout_reason=scout_result.get("reason", ""),
        confirmer_action=confirm_result.get("action", ""),
        confirmer_confidence=confirm_result.get("confidence"),
        confirmer_reason=confirm_result.get("reason", ""),
        filters_log=signal.as_log_dict(),
    )

    # Mark the S/R level as traded
    if level:
        SRLevelModel.objects.filter(
            symbol=symbol, price=level.price
        ).update(traded=True)

    logger.info(
        "Trade opened: %s %s @ %.5f ticket=%d db_id=%s",
        symbol, signal.action, result.price, result.ticket, trade.pk,
    )


# ---------------------------------------------------------------------------
# Exit monitor task
# ---------------------------------------------------------------------------


@shared_task(
    name="trading.tasks.monitor_exits",
    bind=True,
    max_retries=0,
    ignore_result=True,
    time_limit=55,
    soft_time_limit=45,
)
def monitor_exits(self: Any) -> None:
    """
    Check all open trades for exit conditions every minute.

    For each open trade:
        1. Fetch current price from MT5
        2. Call AI exit model for HOLD/CLOSE recommendation
        3. Pass to TradeManager.manage_open_trade()
        4. Execute close if recommended
    """
    from trading.models import Trade, BotStatus
    from trading.binance_connector import get_connector, ConnectorError
    from trading.trade_manager import TradeManager, ActiveTrade
    from trading.sr_engine import SRLevelData
    from trading.instrument import get_pip_size

    for account_type in ("DEMO", "REAL"):
        try:
            _monitor_exits_for_account(account_type)
        except Exception as exc:
            logger.error(
                "monitor_exits: unhandled error for %s: %s",
                account_type, exc, exc_info=True,
            )


def _monitor_exits_for_account(account_type: str) -> None:
    """Monitor exits for a single account type."""
    from trading.models import Trade, BotStatus
    from trading.binance_connector import get_connector, ConnectorError
    from trading.trade_manager import TradeManager, ActiveTrade
    from trading.sr_engine import SRLevelData
    from trading.instrument import get_pip_size

    bot_status = BotStatus.objects.get_status(account_type)

    if bot_status.is_paused:
        return

    connector = get_connector(account_type)
    if not connector.ensure_connected():
        logger.error("monitor_exits [%s]: exchange not connected", account_type)
        return

    manager = TradeManager(connector=connector)

    # Fetch open trades for this account type
    open_trades = Trade.objects.filter(
        exit_time__isnull=True,
        account_type=account_type,
    ).select_related()

    if not open_trades.exists():
        logger.debug("monitor_exits [%s]: no open trades", account_type)
        return

    logger.debug("monitor_exits [%s]: checking %d open trade(s)", account_type, open_trades.count())

    for db_trade in open_trades:
        try:
            _monitor_single_trade(db_trade, connector, manager)
        except Exception as exc:
            logger.error(
                "monitor_exits [%s]: error processing trade %s: %s",
                account_type, db_trade.pk, exc, exc_info=True,
            )


def _monitor_single_trade(db_trade: Any, connector: Any, manager: Any) -> None:
    """Monitor a single open trade — extracted for clarity."""
    from trading.sr_engine import SRLevelData
    from trading.instrument import get_pip_size
    from trading.trade_manager import ActiveTrade
    from trading.binance_connector import ConnectorError

    pip_size = get_pip_size(db_trade.symbol)

    # Check the position still exists in MT5
    positions = connector.get_positions()
    # We don't have the ticket stored in the DB model — look up by comment/symbol
    # In production, the ticket should be stored; here we match by symbol and type
    matching_positions = [
        p for p in positions
        if p.symbol == db_trade.symbol and p.type == db_trade.type
    ]

    if not matching_positions:
        # Position was closed externally (manual close, SL/TP hit)
        logger.info(
            "Trade %s %s appears closed externally — updating DB",
            db_trade.symbol, db_trade.type,
        )
        # Try to find in MT5 history for the actual exit price
        _reconcile_external_close(db_trade, connector)
        return

    position = matching_positions[0]

    # Fetch current price
    try:
        tick = connector.get_tick(db_trade.symbol)
        current_price = (tick.bid + tick.ask) / 2
    except ConnectorError as exc:
        logger.warning("Cannot get tick for %s: %s", db_trade.symbol, exc)
        return

    # Build ActiveTrade from DB record
    entry_level = SRLevelData(
        price=float(db_trade.level_price or 0),
        strength=db_trade.level_strength or 1,
        timeframes=db_trade.level_timeframes.split(",") if db_trade.level_timeframes else [],
    )

    active_trade = ActiveTrade(
        db_id=str(db_trade.pk),
        ticket=position.ticket,
        symbol=db_trade.symbol,
        type=db_trade.type,
        entry_price=float(db_trade.entry_price or 0),
        sl=float(db_trade.sl or 0),
        tp=float(db_trade.tp or 0),
        lot_size=float(db_trade.lot_size or 0),
        entry_level=entry_level,
        entry_time=db_trade.entry_time,
        current_pnl=position.profit,
        pip_size=pip_size,
    )

    # Get AI exit recommendation
    ai_recommendation = _get_ai_exit_recommendation(active_trade, current_price)

    # Evaluate exit conditions
    decision = manager.manage_open_trade(
        trade=active_trade,
        current_price=current_price,
        ai_recommendation=ai_recommendation,
    )

    if decision.should_close:
        logger.info(
            "Closing trade %s %s ticket=%d: %s",
            db_trade.symbol, db_trade.type, position.ticket, decision.reason,
        )
        manager.execute_close(active_trade, decision.reason)


def _get_ai_exit_recommendation(trade: Any, current_price: float) -> str:
    """
    Get AI exit recommendation for an open trade.

    Returns "HOLD" or "CLOSE". Defaults to "HOLD" on any error.
    """
    try:
        from ai.engine import get_ai_engine
        import asyncio

        engine = get_ai_engine()
        context = {
            "symbol": trade.symbol,
            "type": trade.type,
            "entry_price": trade.entry_price,
            "current_price": current_price,
            "sl": trade.sl,
            "tp": trade.tp,
            "bars_open": trade.bars_open,
            "current_pnl": trade.current_pnl,
            "ai_holds": trade.ai_holds,
        }
        result = asyncio.run(engine.exit_check(context))
        return result.get("action", "HOLD").upper()

    except Exception as exc:
        logger.warning("AI exit check failed for %s: %s — defaulting to HOLD", trade.symbol, exc)
        return "HOLD"


def _reconcile_external_close(db_trade: Any, connector: Any) -> None:
    """
    Handle a trade that was closed outside the bot (manual close, SL/TP hit).

    Marks the DB record as closed with the best available exit data.
    """
    from trading.models import Trade
    from django.utils import timezone as dj_timezone
    from datetime import timedelta

    try:
        from_date = db_trade.entry_time
        to_date = dj_timezone.now()

        history = connector.get_history(from_date, to_date)
        matching = [
            h for h in history
            if h.symbol == db_trade.symbol
        ]

        if matching:
            latest = max(matching, key=lambda h: h.time)
            Trade.objects.filter(pk=db_trade.pk).update(
                exit_price=latest.price,
                exit_time=dj_timezone.make_aware(
                    latest.time, dj_timezone.utc
                ) if latest.time.tzinfo is None else latest.time,
                pnl=latest.profit,
                exit_reason="External close (MT5 SL/TP or manual)",
            )
        else:
            # No history found — mark as closed with no data
            Trade.objects.filter(pk=db_trade.pk).update(
                exit_time=dj_timezone.now(),
                exit_reason="External close — history unavailable",
            )

    except Exception as exc:
        logger.error("Failed to reconcile external close for trade %s: %s", db_trade.pk, exc)


# ---------------------------------------------------------------------------
# Health check task
# ---------------------------------------------------------------------------


@shared_task(
    name="trading.tasks.health_check",
    bind=True,
    max_retries=0,
    ignore_result=True,
    time_limit=25,
    soft_time_limit=20,
)
def health_check(self: Any) -> None:
    """
    Check MT5 connectivity and update BotStatus.

    Runs every 30 seconds via CELERY_BEAT_SCHEDULE.
    Updates account balance/equity snapshot and connection state.
    """
    from trading.models import BotStatus
    from trading.binance_connector import get_connector, ConnectorError

    for account_type in ("DEMO", "REAL"):
        connector = get_connector(account_type)
        bot_status = BotStatus.objects.get_status(account_type)

        try:
            if not connector.ensure_connected():
                detail = getattr(connector, "_last_error", "unknown")
                msg = f"Health check failed [{account_type}]: {detail}"
                bot_status.mark_disconnected(msg)
                logger.warning("health_check [%s]: %s", account_type, msg)
                continue

            account = connector.get_account_info()
            bot_status.mark_connected(
                balance=account.balance,
                equity=account.equity,
            )
            logger.debug(
                "health_check [%s]: exchange ok - balance=%.2f equity=%.2f",
                account_type, account.balance, account.equity,
            )

        except ConnectorError as exc:
            bot_status.mark_disconnected(str(exc))
            logger.error("health_check [%s]: ConnectorError: %s", account_type, exc)

        except Exception as exc:
            bot_status.mark_disconnected(f"Health check error: {exc}")
            logger.error("health_check [%s]: unexpected error: %s", account_type, exc, exc_info=True)
