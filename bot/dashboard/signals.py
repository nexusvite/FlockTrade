"""
dashboard/signals.py

Django signal handlers that push real-time events to all connected
WebSocket clients via the ``live_feed`` Redis channel group.

Signal → WebSocket flow
-----------------------

    Django ORM save / explicit send()
        │
        ▼
    Signal handler (this file)
        │  channel_layer.group_send(...)   [async-to-sync bridge]
        ▼
    Redis channel layer  (channels_redis)
        │
        ▼
    LiveFeedConsumer.send_*()  (one call per connected browser tab)
        │
        ▼
    WebSocket → React dashboard

How to connect signals
-----------------------
Signals are registered in ``dashboard/apps.py`` → ``DashboardConfig.ready()``.
The ``AppConfig.ready()`` hook is the canonical place to import signal
receivers in Django so they are wired up exactly once per process start.

Usage from other apps (trading / ai)
--------------------------------------
Signal senders import and call the ``send_*`` helpers directly:

    # In trading/tasks.py after opening a trade:
    from dashboard.signals import notify_trade_created
    notify_trade_created(trade)

    # In ai/engine.py after saving a decision:
    from dashboard.signals import notify_ai_decision
    notify_ai_decision(decision)

    # In trading/tasks.py when bot status changes:
    from dashboard.signals import notify_bot_status_change
    notify_bot_status_change(status="paused", reason="...", triggered_by="admin")

Alternatively, if you use Django signals (post_save) the handlers below are
wired to the ``trading.Trade``, ``ai.AIDecision`` and a custom
``bot_status_changed`` signal automatically via AppConfig.

Thread/async safety
-------------------
Signal handlers run in the Django ORM thread (synchronous context).
``asgiref.sync.async_to_sync`` is used to call the async channel layer from
sync code safely.  Each call spawns a small coroutine on the event loop for
the current thread.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.dispatch import Signal, receiver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom signals
# These can be imported and sent from anywhere in the codebase.
# ---------------------------------------------------------------------------

#: Fired when the bot's operational status changes (paused / resumed /
#: MT5 connect / MT5 disconnect).
bot_status_changed = Signal()
# Providing args (for documentation purposes only — Django signals are
# keyword-only at the call site):
#   status        str   — "paused" | "running" | "connected" | "disconnected"
#   reason        str   — human-readable description
#   triggered_by  str   — username or "system"

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

LIVE_FEED_GROUP = "live_feed"


# ---------------------------------------------------------------------------
# Low-level group_send helper
# ---------------------------------------------------------------------------

def _push_to_group(message: dict) -> None:
    """
    Send *message* to the ``live_feed`` Redis channel group synchronously.

    This is the single point where all signal handlers call into the
    async channel layer.  If the channel layer is not configured (e.g.
    during unit tests without Redis), the push is silently skipped after
    logging a warning so the application does not crash.

    Parameters
    ----------
    message:
        A dict with at minimum a ``"type"`` key whose value matches one of
        the handler method names on ``LiveFeedConsumer``
        (e.g. ``"send_trade_update"``).
    """
    channel_layer = get_channel_layer()

    if channel_layer is None:
        logger.warning(
            "Channel layer is not configured — skipping live push (type=%s). "
            "Ensure CHANNEL_LAYERS is set in settings.py.",
            message.get("type"),
        )
        return

    try:
        async_to_sync(channel_layer.group_send)(LIVE_FEED_GROUP, message)
    except Exception as exc:  # noqa: BLE001
        # Never let a WebSocket push crash the trading engine.
        logger.error(
            "Failed to push message to live_feed group (type=%s): %s — %s",
            message.get("type"),
            type(exc).__name__,
            exc,
        )


def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public notify helpers
# Called directly from trading / ai modules.
# ---------------------------------------------------------------------------

def notify_trade_created(trade: Any) -> None:
    """
    Push a ``trade_update`` (event=trade_opened) message to all dashboard clients.

    Parameters
    ----------
    trade:
        A ``trading.models.Trade`` instance that was just persisted.
        Fields are accessed by attribute name so the function remains
        loosely coupled to the model definition.
    """
    payload: dict = {
        "event": "trade_opened",
        "trade_id": str(trade.id),
        "symbol": trade.symbol,
        "type": trade.type,
        "entry_price": float(trade.entry_price) if trade.entry_price is not None else None,
        "sl": float(trade.sl) if trade.sl is not None else None,
        "tp": float(trade.tp) if trade.tp is not None else None,
        "lot_size": float(trade.lot_size) if trade.lot_size is not None else None,
        "exit_price": None,
        "pnl": None,
        "timestamp": (
            trade.entry_time.isoformat()
            if trade.entry_time is not None
            else _utcnow_iso()
        ),
    }

    logger.debug(
        "Pushing trade_opened to live_feed: trade_id=%s symbol=%s",
        payload["trade_id"],
        payload["symbol"],
    )

    _push_to_group({"type": "send_trade_update", "payload": payload})


def notify_trade_closed(trade: Any) -> None:
    """
    Push a ``trade_update`` (event=trade_closed) message to all dashboard clients.

    Parameters
    ----------
    trade:
        A ``trading.models.Trade`` instance whose ``exit_price``,
        ``exit_time``, and ``pnl`` have been populated.
    """
    payload: dict = {
        "event": "trade_closed",
        "trade_id": str(trade.id),
        "symbol": trade.symbol,
        "type": trade.type,
        "entry_price": float(trade.entry_price) if trade.entry_price is not None else None,
        "sl": float(trade.sl) if trade.sl is not None else None,
        "tp": float(trade.tp) if trade.tp is not None else None,
        "lot_size": float(trade.lot_size) if trade.lot_size is not None else None,
        "exit_price": float(trade.exit_price) if trade.exit_price is not None else None,
        "pnl": float(trade.pnl) if trade.pnl is not None else None,
        "exit_reason": getattr(trade, "exit_reason", None),
        "timestamp": (
            trade.exit_time.isoformat()
            if trade.exit_time is not None
            else _utcnow_iso()
        ),
    }

    logger.debug(
        "Pushing trade_closed to live_feed: trade_id=%s symbol=%s pnl=%s",
        payload["trade_id"],
        payload["symbol"],
        payload["pnl"],
    )

    _push_to_group({"type": "send_trade_update", "payload": payload})


def notify_ai_decision(decision: Any) -> None:
    """
    Push an ``ai_decision`` event to all dashboard clients.

    Parameters
    ----------
    decision:
        An ``ai.models.AIDecision`` instance that was just saved.
    """
    payload: dict = {
        "decision_id": str(decision.id),
        "symbol": decision.symbol,
        "role": decision.role,
        "model": decision.model,
        "action": decision.action,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "latency_ms": decision.latency_ms,
        "cost_usd": float(decision.cost_usd) if decision.cost_usd is not None else None,
        "timestamp": (
            decision.timestamp.isoformat()
            if decision.timestamp is not None
            else _utcnow_iso()
        ),
    }

    logger.debug(
        "Pushing ai_decision to live_feed: symbol=%s role=%s action=%s confidence=%s",
        payload["symbol"],
        payload["role"],
        payload["action"],
        payload["confidence"],
    )

    _push_to_group({"type": "send_ai_decision", "payload": payload})


def notify_bot_status_change(
    status: str,
    reason: str = "",
    triggered_by: str | None = None,
) -> None:
    """
    Push a ``status_update`` event to all dashboard clients.

    Parameters
    ----------
    status:
        One of ``"paused"``, ``"running"``, ``"connected"``, ``"disconnected"``.
    reason:
        Human-readable description of why the status changed.
    triggered_by:
        Username of the operator who triggered the change, or ``"system"``
        for automated changes (e.g. daily loss limit hit).
    """
    payload: dict = {
        "status": status,
        "reason": reason,
        "triggered_by": triggered_by or "system",
        "timestamp": _utcnow_iso(),
    }

    logger.info(
        "Pushing status_update to live_feed: status=%s reason=%r triggered_by=%s",
        status,
        reason,
        payload["triggered_by"],
    )

    _push_to_group({"type": "send_status_update", "payload": payload})


def notify_price_update(symbol: str, bid: float, ask: float, spread: float) -> None:
    """
    Push a live price tick to all dashboard clients.

    Parameters
    ----------
    symbol:
        Instrument symbol, e.g. ``"USDJPYm"``.
    bid:
        Current bid price.
    ask:
        Current ask price.
    spread:
        Spread in pips.
    """
    payload: dict = {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "timestamp": _utcnow_iso(),
    }

    _push_to_group({"type": "send_price_update", "payload": payload})


# ---------------------------------------------------------------------------
# Django post_save signal receivers
# These fire automatically when ORM objects are saved.
# They are connected in DashboardConfig.ready() (see apps.py) via:
#     from dashboard import signals  # noqa: F401
# ---------------------------------------------------------------------------

def on_trade_created(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """
    ``post_save`` receiver for ``trading.models.Trade``.

    Fires a ``trade_opened`` WebSocket event only on INSERT (created=True)
    so that routine field updates (e.g. bars_held counter) do not generate
    spurious notifications.
    """
    if not created:
        return

    try:
        notify_trade_created(instance)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "on_trade_created signal handler failed for trade_id=%s: %s",
            getattr(instance, "id", "?"),
            exc,
        )


def on_trade_closed(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """
    ``post_save`` receiver for ``trading.models.Trade``.

    Fires a ``trade_closed`` WebSocket event when an existing trade record
    gains an ``exit_price`` (i.e. the trade was just closed).

    Uses ``update_fields`` from kwargs when available so we only notify
    when a genuine close happens, not every save.
    """
    if created:
        return

    update_fields = kwargs.get("update_fields")

    # If update_fields is specified, only notify when exit_price is being set.
    if update_fields is not None and "exit_price" not in update_fields:
        return

    # Guard: do not notify if exit_price is still null (trade still open).
    if getattr(instance, "exit_price", None) is None:
        return

    try:
        notify_trade_closed(instance)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "on_trade_closed signal handler failed for trade_id=%s: %s",
            getattr(instance, "id", "?"),
            exc,
        )


def on_ai_decision(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """
    ``post_save`` receiver for ``ai.models.AIDecision``.

    Only fires on INSERT because AI decisions are immutable records.
    """
    if not created:
        return

    try:
        notify_ai_decision(instance)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "on_ai_decision signal handler failed for decision_id=%s: %s",
            getattr(instance, "id", "?"),
            exc,
        )


@receiver(bot_status_changed)
def on_bot_status_change(
    sender: Any,
    status: str,
    reason: str = "",
    triggered_by: str | None = None,
    **kwargs: Any,
) -> None:
    """
    Receiver for the custom ``bot_status_changed`` signal.

    To trigger this from anywhere in the codebase:

        from dashboard.signals import bot_status_changed

        bot_status_changed.send(
            sender=None,
            status="paused",
            reason="Daily loss limit reached",
            triggered_by="system",
        )
    """
    try:
        notify_bot_status_change(
            status=status,
            reason=reason,
            triggered_by=triggered_by,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "on_bot_status_change signal handler failed: status=%s %s",
            status,
            exc,
        )
