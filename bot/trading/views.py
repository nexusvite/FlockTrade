"""
API Views for the Trading app.

All views require JWT authentication (configured in settings.py via
REST_FRAMEWORK DEFAULT_AUTHENTICATION_CLASSES).

Endpoints:
    GET  /api/trades/              — Paginated trade history
    GET  /api/trades/{id}/         — Trade detail with AI reasoning
    GET  /api/levels/              — Current S/R levels
    GET  /api/performance/         — Win rate and P&L statistics
    GET  /api/status/              — Bot status
    POST /api/control/             — Pause / resume / stop / start
    GET  /api/config/              — Current configuration
    PATCH /api/config/             — Update configuration

Permissions:
    - Viewer: GET endpoints
    - Trader: GET + POST /api/control/
    - Admin:  All including PATCH /api/config/
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from trading.models import BotStatus, DailyStats, SRLevel, Trade
from trading.serializers import (
    BotControlSerializer,
    BotStatusSerializer,
    ConfigUpdateSerializer,
    DailyStatsSerializer,
    PerformanceSerializer,
    SRLevelSerializer,
    TradeDetailSerializer,
    TradeListSerializer,
)

logger = logging.getLogger("trading.views")


# ---------------------------------------------------------------------------
# Trade views
# ---------------------------------------------------------------------------


class TradeListView(generics.ListAPIView):
    """
    GET /api/trades/

    Returns paginated trade history, newest first.

    Query params:
        symbol      — Filter by symbol (e.g. ?symbol=USDJPYm)
        type        — Filter by BUY/SELL
        is_open     — Filter open/closed trades (?is_open=true)
        ordering    — Any field, e.g. ?ordering=-entry_time
        search      — Full-text search on symbol and exit_reason
    """

    serializer_class = TradeListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["symbol", "type"]
    search_fields = ["symbol", "exit_reason", "scout_reason", "confirmer_reason"]
    ordering_fields = ["entry_time", "exit_time", "pnl", "level_strength"]
    ordering = ["-entry_time"]

    def get_queryset(self):
        qs = Trade.objects.all()

        # Filter open/closed
        is_open = self.request.query_params.get("is_open")
        if is_open is not None:
            if is_open.lower() in ("true", "1"):
                qs = qs.filter(exit_time__isnull=True)
            elif is_open.lower() in ("false", "0"):
                qs = qs.filter(exit_time__isnull=False)

        return qs


class TradeDetailView(generics.RetrieveAPIView):
    """
    GET /api/trades/{id}/

    Returns full trade detail including AI reasoning and filter log.
    """

    serializer_class = TradeDetailSerializer
    permission_classes = [IsAuthenticated]
    queryset = Trade.objects.all()
    lookup_field = "pk"


# ---------------------------------------------------------------------------
# S/R Level view
# ---------------------------------------------------------------------------


class SRLevelListView(generics.ListAPIView):
    """
    GET /api/levels/

    Returns current S/R levels, optionally filtered by symbol.
    Injects current prices for distance calculation when available.

    Query params:
        symbol   — Filter by symbol (e.g. ?symbol=USDJPYm)
        strength — Minimum strength (?strength=3)
        traded   — Filter traded/untradeable (?traded=false)
    """

    serializer_class = SRLevelSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["symbol", "traded"]
    ordering_fields = ["strength", "price", "last_touched"]
    ordering = ["-strength"]

    def get_queryset(self):
        qs = SRLevel.objects.all()

        min_strength = self.request.query_params.get("strength")
        if min_strength is not None:
            try:
                qs = qs.filter(strength__gte=int(min_strength))
            except ValueError:
                pass

        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # Optionally inject current prices for distance calculation
        # In production, these come from a Redis cache updated by the scanner
        context["current_prices"] = _get_current_prices_from_cache()
        return context


# ---------------------------------------------------------------------------
# Performance view
# ---------------------------------------------------------------------------


class PerformanceView(APIView):
    """
    GET /api/performance/

    Returns aggregated performance statistics.

    Query params:
        period — "today" | "7d" | "30d" | "all" (default: "30d")
        symbol — Filter by symbol (optional)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        period = request.query_params.get("period", "30d")
        symbol = request.query_params.get("symbol")

        qs = Trade.objects.filter(exit_time__isnull=False)

        # Apply time filter
        now = timezone.now()
        if period == "today":
            qs = qs.filter(exit_time__date=now.date())
        elif period == "7d":
            qs = qs.filter(exit_time__gte=now - timezone.timedelta(days=7))
        elif period == "30d":
            qs = qs.filter(exit_time__gte=now - timezone.timedelta(days=30))
        # "all" — no time filter

        if symbol:
            qs = qs.filter(symbol=symbol)

        # Aggregate stats
        agg = qs.aggregate(
            total_trades=Count("id"),
            wins=Count("id", filter=Q(pnl__gt=0)),
            losses=Count("id", filter=Q(pnl__lt=0)),
            scratches=Count("id", filter=Q(pnl=0)),
            total_pnl=Sum("pnl"),
            avg_pnl=Avg("pnl"),
            best_trade=Max("pnl"),
            worst_trade=Min("pnl"),
            avg_bars=Avg("bars_held"),
        )

        total = agg["total_trades"] or 0
        wins = agg["wins"] or 0
        win_rate = round((wins / total) * 100, 2) if total > 0 else 0.0

        # Per-symbol breakdown
        by_symbol = list(
            qs.values("symbol").annotate(
                trades=Count("id"),
                wins=Count("id", filter=Q(pnl__gt=0)),
                losses=Count("id", filter=Q(pnl__lt=0)),
                pnl=Sum("pnl"),
            ).order_by("-pnl")
        )

        # Per-strength breakdown
        by_strength = list(
            qs.values("level_strength").annotate(
                trades=Count("id"),
                wins=Count("id", filter=Q(pnl__gt=0)),
                pnl=Sum("pnl"),
            ).order_by("-level_strength")
        )

        data = {
            "period": period,
            "total_trades": total,
            "wins": wins,
            "losses": agg["losses"] or 0,
            "scratches": agg["scratches"] or 0,
            "win_rate": win_rate,
            "total_pnl": agg["total_pnl"] or Decimal("0"),
            "avg_pnl_per_trade": agg["avg_pnl"] or Decimal("0"),
            "best_trade": agg["best_trade"] or Decimal("0"),
            "worst_trade": agg["worst_trade"] or Decimal("0"),
            "avg_bars_held": round(agg["avg_bars"] or 0, 1),
            "by_symbol": by_symbol,
            "by_strength": by_strength,
        }

        serializer = PerformanceSerializer(data)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Daily stats view
# ---------------------------------------------------------------------------


class DailyStatsListView(generics.ListAPIView):
    """
    GET /api/daily-stats/

    Returns daily performance statistics, newest first.

    Query params:
        days — Number of days to return (default: 30)
    """

    serializer_class = DailyStatsSerializer
    permission_classes = [IsAuthenticated]
    ordering = ["-date"]

    def get_queryset(self):
        days = self.request.query_params.get("days", 30)
        try:
            days = int(days)
        except ValueError:
            days = 30

        cutoff = timezone.now().date() - timezone.timedelta(days=days)
        return DailyStats.objects.filter(date__gte=cutoff).order_by("-date")


# ---------------------------------------------------------------------------
# Bot status view
# ---------------------------------------------------------------------------


class BotStatusView(APIView):
    """
    GET /api/status/

    Returns the current bot status snapshot.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        status_obj = BotStatus.objects.get_status()
        serializer = BotStatusSerializer(status_obj)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Bot control view
# ---------------------------------------------------------------------------


class BotControlView(APIView):
    """
    POST /api/control/

    Control bot operation. Requires Trader or Admin role.

    Request body:
        { "action": "pause" | "resume" | "stop" | "start" }

    Responses:
        200 — Action applied, returns new BotStatus
        400 — Invalid action
        403 — Insufficient permissions
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        # Require trader or admin role
        _require_trader_or_admin(request)

        serializer = BotControlSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data["action"]
        bot_status = BotStatus.objects.get_status()

        if action == "pause":
            BotStatus.objects.filter(pk=1).update(is_paused=True)
            logger.info("Bot paused by user %s", request.user.username)
            message = "Bot paused."

        elif action == "resume":
            BotStatus.objects.filter(pk=1).update(is_paused=False)
            logger.info("Bot resumed by user %s", request.user.username)
            message = "Bot resumed."

        elif action == "stop":
            BotStatus.objects.filter(pk=1).update(is_running=False, is_paused=False)
            logger.info("Bot stopped by user %s", request.user.username)
            message = "Bot stopped."

        elif action == "start":
            BotStatus.objects.filter(pk=1).update(is_running=True, is_paused=False)
            logger.info("Bot started by user %s", request.user.username)
            message = "Bot started."

        else:
            return Response(
                {"error": f"Unknown action: {action}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bot_status.refresh_from_db()
        return Response(
            {
                "message": message,
                "status": BotStatusSerializer(bot_status).data,
            }
        )


# ---------------------------------------------------------------------------
# Configuration view
# ---------------------------------------------------------------------------


class ConfigView(APIView):
    """
    GET  /api/config/   — Return current bot configuration
    PATCH /api/config/  — Update configuration (Admin only)

    Settings are read from django.conf.settings and updated in-process.
    Note: In-process updates are lost on worker restart. For persistence,
    store config in a database model (future enhancement).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        config = {
            "symbols": getattr(settings, "SYMBOLS", []),
            "lot_size_forex": getattr(settings, "LOT_SIZE_FOREX", 1.0),
            "lot_size_gold": getattr(settings, "LOT_SIZE_GOLD", 0.1),
            "tp_pips_forex": getattr(settings, "TP_PIPS_FOREX", 2),
            "sl_pips_forex": getattr(settings, "SL_PIPS_FOREX", 5),
            "tp_pips_gold": getattr(settings, "TP_PIPS_GOLD", 20),
            "sl_pips_gold": getattr(settings, "SL_PIPS_GOLD", 50),
            "max_daily_losses": getattr(settings, "MAX_DAILY_LOSSES", 3),
            "max_daily_loss_usd": getattr(settings, "MAX_DAILY_LOSS_USD", 100),
            "scout_model": getattr(settings, "SCOUT_MODEL", ""),
            "confirmer_model": getattr(settings, "CONFIRMER_MODEL", ""),
            "asia_start": getattr(settings, "ASIA_START", 1),
            "asia_end": getattr(settings, "ASIA_END", 6),
            "london_start": getattr(settings, "LONDON_START", 8),
            "london_end": getattr(settings, "LONDON_END", 12),
            "ny_start": getattr(settings, "NY_START", 13),
            "ny_end": getattr(settings, "NY_END", 20),
        }
        return Response(config)

    def patch(self, request: Request) -> Response:
        # Require admin role for config changes
        _require_admin(request)

        serializer = ConfigUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        updated: list[str] = []

        # Apply updates to the live settings object
        # (persists for the lifetime of this worker process)
        setting_map = {
            "symbols": "SYMBOLS",
            "lot_size_forex": "LOT_SIZE_FOREX",
            "lot_size_gold": "LOT_SIZE_GOLD",
            "tp_pips_forex": "TP_PIPS_FOREX",
            "sl_pips_forex": "SL_PIPS_FOREX",
            "tp_pips_gold": "TP_PIPS_GOLD",
            "sl_pips_gold": "SL_PIPS_GOLD",
            "max_daily_losses": "MAX_DAILY_LOSSES",
            "max_daily_loss_usd": "MAX_DAILY_LOSS_USD",
            "scout_model": "SCOUT_MODEL",
            "confirmer_model": "CONFIRMER_MODEL",
        }

        for field_name, setting_name in setting_map.items():
            if field_name in data:
                setattr(settings, setting_name, data[field_name])
                updated.append(setting_name)

        logger.info(
            "Config updated by %s: %s", request.user.username, ", ".join(updated)
        )

        return Response(
            {
                "message": f"Updated: {', '.join(updated)}",
                "updated_fields": updated,
            }
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_trader_or_admin(request: Request) -> None:
    """
    Raise PermissionDenied if user does not have trader or admin role.

    Reads from request.user.profile.role if available.
    Falls back to staff/superuser check for backwards compatibility.
    """
    user = request.user
    if user.is_staff or user.is_superuser:
        return

    try:
        role = user.profile.role  # type: ignore[attr-defined]
        if role in ("admin", "trader"):
            return
    except AttributeError:
        pass

    raise PermissionDenied("Trader or Admin role required.")


def _require_admin(request: Request) -> None:
    """
    Raise PermissionDenied if user does not have admin role.
    """
    user = request.user
    if user.is_superuser:
        return

    try:
        role = user.profile.role  # type: ignore[attr-defined]
        if role == "admin":
            return
    except AttributeError:
        pass

    raise PermissionDenied("Admin role required.")


def _get_current_prices_from_cache() -> dict[str, float]:
    """
    Attempt to fetch current prices from Django's Redis cache.

    The scanner writes prices to cache each scan as:
        Key: "current_price:{symbol}"
        Value: float

    Returns empty dict if cache is unavailable.
    """
    from django.core.cache import cache
    from django.conf import settings as djsettings

    symbols: list[str] = getattr(djsettings, "SYMBOLS", [])
    prices: dict[str, float] = {}

    for symbol in symbols:
        price = cache.get(f"current_price:{symbol}")
        if price is not None:
            prices[symbol] = float(price)

    return prices
