"""
dashboard/consumers.py

Async Django Channels WebSocket consumer for the FlockTrade live feed.

Every browser tab that opens ws/live/ creates one LiveFeedConsumer instance.
After successful JWT authentication, the socket is added to the shared
"live_feed" Redis group so that trade/AI/status events broadcast to ALL
connected clients simultaneously.

Authentication flow
-------------------
1. Client connects to  ws://host/ws/live/?token=<JWT-access-token>
2. Consumer validates the token via SimpleJWT's UntypedToken.
3. On success, the Django User is loaded and stored on ``self.user``.
4. On failure, the socket is closed immediately with code 4001.

Message format (server → client)
---------------------------------
Every outbound message is JSON with at least a ``type`` field, e.g.:

    {"type": "trade_update",   "payload": {...}}
    {"type": "price_update",   "payload": {...}}
    {"type": "ai_decision",    "payload": {...}}
    {"type": "status_update",  "payload": {...}}

Inbound messages (client → server)
------------------------------------
Clients may send a JSON ping to keep the connection alive:

    {"type": "ping"}

The consumer responds with:

    {"type": "pong", "timestamp": "<ISO-8601>"}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.auth.models import User as DjangoUser

logger = logging.getLogger(__name__)

# All authenticated consumers join this single broadcast group.
LIVE_FEED_GROUP = "live_feed"


def _get_token_from_scope(scope: dict) -> str | None:
    """
    Extract the JWT access token from the WebSocket query string.

    Django Channels populates ``scope["query_string"]`` as raw bytes, e.g.
    b"token=eyJhbGci..."  We parse it manually to avoid importing urllib.parse
    in the hot path and to keep the implementation dependency-free.

    Returns the token string, or None if the parameter is missing/empty.
    """
    query_string: bytes = scope.get("query_string", b"")
    if not query_string:
        return None

    for part in query_string.decode("utf-8", errors="replace").split("&"):
        if "=" in part:
            key, _, value = part.partition("=")
            if key.strip() == "token" and value.strip():
                return value.strip()
    return None


async def _authenticate_token(token: str) -> DjangoUser | None:
    """
    Validate a SimpleJWT access token and return the corresponding User.

    Runs ``UntypedToken(token)`` which raises ``TokenError`` on any invalid,
    expired, or malformed token.  The user ID is extracted from the payload
    and fetched from the database with ``database_sync_to_async``.

    Returns the User object on success, or None on any validation failure.
    """
    from channels.db import database_sync_to_async
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import UntypedToken
    from rest_framework_simplejwt.settings import api_settings as jwt_settings

    try:
        # Validate signature, expiry, and token type in one call.
        validated = UntypedToken(token)
    except TokenError as exc:
        logger.warning("WebSocket JWT validation failed: %s", exc)
        return None

    # Pull user_id from the payload using the configured claim name.
    user_id_claim = jwt_settings.USER_ID_CLAIM  # usually "user_id"
    user_id = validated.payload.get(user_id_claim)
    if user_id is None:
        logger.warning("WebSocket JWT missing user_id claim")
        return None

    try:
        user: DjangoUser = await database_sync_to_async(
            User.objects.select_related("profile").get
        )(pk=user_id, is_active=True)
        return user
    except User.DoesNotExist:
        logger.warning("WebSocket JWT references non-existent or inactive user id=%s", user_id)
        return None


class LiveFeedConsumer(AsyncWebsocketConsumer):
    """
    Real-time WebSocket consumer for the FlockTrade dashboard live feed.

    One instance per connected browser tab.  All instances in the
    ``live_feed`` Redis group receive the same broadcast messages from
    Django signals (signals.py) and Celery tasks.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """
        Authenticate via JWT query-string token, then join the live_feed group.

        Closes with code 4001 (Unauthorized) on any auth failure so the
        client knows to redirect to the login page rather than retry.
        """
        token = _get_token_from_scope(self.scope)

        if not token:
            logger.warning(
                "WebSocket connection rejected — no token in query string "
                "(path=%s)",
                self.scope.get("path"),
            )
            await self.close(code=4001)
            return

        user = await _authenticate_token(token)

        if user is None:
            logger.warning(
                "WebSocket connection rejected — invalid/expired JWT "
                "(path=%s)",
                self.scope.get("path"),
            )
            await self.close(code=4001)
            return

        # Attach the authenticated user to this consumer instance.
        self.user: DjangoUser = user
        self.channel_name: str  # set by Channels base class before connect()

        # Join the shared broadcast group.
        await self.channel_layer.group_add(LIVE_FEED_GROUP, self.channel_name)
        await self.accept()

        logger.info(
            "WebSocket connected: user=%s channel=%s",
            self.user.username,
            self.channel_name,
        )

        # Send an immediate welcome so the client knows auth succeeded.
        await self._send_json(
            {
                "type": "connected",
                "payload": {
                    "user": self.user.username,
                    "message": "Connected to FlockTrade live feed",
                    "timestamp": _utcnow_iso(),
                },
            }
        )

    async def disconnect(self, close_code: int) -> None:
        """
        Leave the live_feed group on disconnect.

        This is always called regardless of whether ``connect`` succeeded,
        so we guard against the case where ``self.user`` was never set.
        """
        username = getattr(self, "user", AnonymousUser()).username or "anonymous"

        if hasattr(self, "channel_name"):
            await self.channel_layer.group_discard(LIVE_FEED_GROUP, self.channel_name)
            logger.info(
                "WebSocket disconnected: user=%s channel=%s code=%s",
                username,
                self.channel_name,
                close_code,
            )

    async def receive(self, text_data: str | None = None, bytes_data: bytes | None = None) -> None:
        """
        Handle messages sent from the client to the server.

        Currently only ``{"type": "ping"}`` is processed.  All other
        messages are logged and silently discarded to keep the consumer
        stateless and easy to reason about.
        """
        if not text_data:
            return

        try:
            data: dict = json.loads(text_data)
        except json.JSONDecodeError:
            logger.debug(
                "WebSocket received non-JSON data from user=%s",
                getattr(self, "user", AnonymousUser()).username,
            )
            return

        msg_type = data.get("type", "")

        if msg_type == "ping":
            await self._send_json({"type": "pong", "timestamp": _utcnow_iso()})
        else:
            logger.debug(
                "WebSocket received unhandled message type=%r from user=%s",
                msg_type,
                getattr(self, "user", AnonymousUser()).username,
            )

    # ------------------------------------------------------------------
    # Broadcast handlers
    # These methods are called by the Channels layer when a message is
    # sent to the "live_feed" group (typically from signals.py).
    # The method name must match the "type" key in the group_send call
    # with dots replaced by underscores.
    # ------------------------------------------------------------------

    async def send_trade_update(self, event: dict) -> None:
        """
        Broadcast a trade lifecycle event to this consumer's WebSocket client.

        Called when the channel layer delivers a ``type: send_trade_update``
        message to the ``live_feed`` group.  Fired by the ``on_trade_created``
        and ``on_trade_closed`` signal handlers in signals.py.

        Expected event structure::

            {
                "type": "send_trade_update",
                "payload": {
                    "event":        "trade_opened" | "trade_closed",
                    "trade_id":     str,         # UUID
                    "symbol":       str,         # e.g. "USDJPYm"
                    "type":         str,         # "BUY" | "SELL"
                    "entry_price":  float,
                    "sl":           float,
                    "tp":           float,
                    "lot_size":     float,
                    "exit_price":   float | None,
                    "pnl":          float | None,
                    "timestamp":    str,         # ISO-8601
                }
            }
        """
        await self._send_json({"type": "trade_update", "payload": event["payload"]})

    async def send_price_update(self, event: dict) -> None:
        """
        Broadcast a live price tick to this consumer's WebSocket client.

        Called when the channel layer delivers a ``type: send_price_update``
        message to the ``live_feed`` group.  Fired periodically by the
        MT5 health-check Celery task or price-feed task.

        Expected event structure::

            {
                "type": "send_price_update",
                "payload": {
                    "symbol":   str,    # e.g. "USDJPYm"
                    "bid":      float,
                    "ask":      float,
                    "spread":   float,  # pips
                    "timestamp": str,   # ISO-8601
                }
            }
        """
        await self._send_json({"type": "price_update", "payload": event["payload"]})

    async def send_ai_decision(self, event: dict) -> None:
        """
        Broadcast an AI scout/confirmer decision to this consumer's client.

        Called when the channel layer delivers a ``type: send_ai_decision``
        message to the ``live_feed`` group.  Fired by the ``on_ai_decision``
        signal handler in signals.py after an AIDecision record is saved.

        Expected event structure::

            {
                "type": "send_ai_decision",
                "payload": {
                    "decision_id":  str,    # UUID
                    "symbol":       str,
                    "role":         str,    # "scout" | "confirmer"
                    "model":        str,    # e.g. "anthropic/claude-haiku-4.5"
                    "action":       str,    # "BUY" | "SELL" | "SKIP" | "CONFIRM" | "REJECT"
                    "confidence":   int,    # 0-100
                    "reason":       str,
                    "latency_ms":   int,
                    "cost_usd":     float,
                    "timestamp":    str,    # ISO-8601
                }
            }
        """
        await self._send_json({"type": "ai_decision", "payload": event["payload"]})

    async def send_status_update(self, event: dict) -> None:
        """
        Broadcast a bot status change to this consumer's WebSocket client.

        Called when the channel layer delivers a ``type: send_status_update``
        message to the ``live_feed`` group.  Fired by ``on_bot_status_change``
        in signals.py when the bot is paused, resumed, connected, or
        disconnected from MT5.

        Expected event structure::

            {
                "type": "send_status_update",
                "payload": {
                    "status":       str,    # "paused" | "running" | "connected" | "disconnected"
                    "reason":       str,    # human-readable description
                    "triggered_by": str | None,  # username or "system"
                    "timestamp":    str,    # ISO-8601
                }
            }
        """
        await self._send_json({"type": "status_update", "payload": event["payload"]})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_json(self, data: dict) -> None:
        """
        Serialise *data* to JSON and send it over the WebSocket.

        Swallows any send errors that arise when the socket closes between
        the time a broadcast is enqueued and when it is delivered, which is
        a normal race condition in async systems.
        """
        try:
            await self.send(text_data=json.dumps(data, default=str))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "WebSocket send failed (socket likely closed): %s — %s",
                type(exc).__name__,
                exc,
            )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()
