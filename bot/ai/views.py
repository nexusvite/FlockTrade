"""
API views for the AI app.

Endpoints:
  GET  /api/ai/decisions/          Paginated AIDecision log (filterable)
  GET  /api/ai/decisions/<uuid>/   Single decision detail
  GET  /api/ai/costs/              Cost breakdown by model and by day

All endpoints require JWT authentication.
Admin-only access enforced for sensitive raw response data.
"""
import logging
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Avg, Count, QuerySet, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import filters, generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .engine import CACHE_PREFIX_DAILY_CALLS, CACHE_PREFIX_DAILY_COST
from .models import AIDecision
from .serializers import (
    AIDecisionFilterSerializer,
    AIDecisionListSerializer,
    AIDecisionSerializer,
    AICostQuerySerializer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AIDecisionListView
# ---------------------------------------------------------------------------

class AIDecisionListView(generics.ListAPIView):
    """
    Paginated list of AI decisions with multi-field filtering.

    GET /api/ai/decisions/

    Query Parameters:
        symbol         Filter by trading pair (e.g. USDJPYm)
        role           Filter by AI role: scout | confirmer | exit
        action         Filter by action: BUY | SELL | SKIP | CONFIRM | REJECT | HOLD | CLOSE | ERROR
        model          Filter by model name (partial match supported)
        min_confidence Only return decisions with confidence >= this value
        date           Filter by UTC date (YYYY-MM-DD)
        search         Full-text search on reason field
        ordering       Field to order by (prefix with - for descending)

    Response:
        Standard DRF paginated response wrapping AIDecisionListSerializer.
        Pagination is set to 25 per page (configured in REST_FRAMEWORK settings).

    Permissions:
        Requires authenticated user (JWT).
    """

    serializer_class = AIDecisionListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["reason", "symbol", "model"]
    ordering_fields = ["timestamp", "confidence", "latency_ms", "cost_usd"]
    ordering = ["-timestamp"]

    def get_queryset(self) -> QuerySet:
        """
        Build and return the filtered queryset.

        Applies all query parameters from AIDecisionFilterSerializer.
        """
        # Validate query params.
        filter_serializer = AIDecisionFilterSerializer(data=self.request.query_params)
        filter_serializer.is_valid()  # We apply valid fields only; invalid are ignored.
        params: dict = filter_serializer.validated_data

        qs: QuerySet = AIDecision.objects.all()

        if symbol := params.get("symbol"):
            qs = qs.filter(symbol=symbol.upper())

        if role := params.get("role"):
            qs = qs.filter(role=role)

        if action := params.get("action"):
            qs = qs.filter(action=action)

        if model := params.get("model"):
            qs = qs.filter(model__icontains=model)

        if min_conf := params.get("min_confidence"):
            qs = qs.filter(confidence__gte=min_conf)

        if date := params.get("date"):
            qs = qs.filter(timestamp__date=date)

        return qs


# ---------------------------------------------------------------------------
# AIDecisionDetailView
# ---------------------------------------------------------------------------

class AIDecisionDetailView(generics.RetrieveAPIView):
    """
    Retrieve a single AI decision with full context and raw response.

    GET /api/ai/decisions/<uuid>/

    Returns the full AIDecisionSerializer including input_context and
    raw_response fields — useful for debugging model outputs.

    Permissions:
        Requires authenticated user (JWT).
    """

    queryset = AIDecision.objects.all()
    serializer_class = AIDecisionSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "pk"


# ---------------------------------------------------------------------------
# AICostView
# ---------------------------------------------------------------------------

class AICostView(APIView):
    """
    AI cost breakdown by model and by day.

    GET /api/ai/costs/

    Query Parameters:
        start   Start date (YYYY-MM-DD). Defaults to first day of current month.
        end     End date (YYYY-MM-DD). Defaults to today.
        model   Optional model filter.

    Response:
    {
        "period": {
            "start": "2026-03-01",
            "end": "2026-03-18"
        },
        "totals": {
            "total_calls": 248,
            "total_cost_usd": "0.036850",
            "avg_latency_ms": 1243.7,
            "by_action": {
                "BUY": 12, "SELL": 9, "SKIP": 210, "CONFIRM": 8,
                "REJECT": 4, "HOLD": 35, "CLOSE": 5, "ERROR": 2
            }
        },
        "by_model": [
            {
                "model": "anthropic/claude-haiku-4.5",
                "total_calls": 210,
                "total_cost_usd": "0.002100",
                "avg_latency_ms": 890.3
            },
            ...
        ],
        "by_day": [
            {
                "date": "2026-03-18",
                "total_calls": 14,
                "total_cost_usd": "0.001800",
                "avg_latency_ms": 1100.0
            },
            ...
        ],
        "live_today": {
            "scout_calls": 120,
            "scout_cost_usd": 0.012000,
            "confirmer_calls": 4,
            "confirmer_cost_usd": 0.008500
        }
    }

    Permissions:
        Requires authenticated user (JWT).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        # Validate and parse query params.
        query_serializer = AICostQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params: dict = query_serializer.validated_data

        start_date = params["start"]
        end_date = params["end"]
        model_filter: str | None = params.get("model")

        # --- Database aggregation ---
        qs: QuerySet = AIDecision.objects.filter(
            timestamp__date__gte=start_date,
            timestamp__date__lte=end_date,
        )
        if model_filter:
            qs = qs.filter(model__icontains=model_filter)

        # Totals.
        totals_agg = qs.aggregate(
            total_calls=Count("id"),
            total_cost_usd=Sum("cost_usd"),
            avg_latency_ms=Avg("latency_ms"),
        )

        # Action breakdown.
        action_counts: dict[str, int] = {}
        for row in qs.values("action").annotate(count=Count("id")):
            action_counts[row["action"]] = row["count"]

        # By-model breakdown.
        by_model: list[dict] = []
        for row in (
            qs.values("model")
            .annotate(
                total_calls=Count("id"),
                total_cost_usd=Sum("cost_usd"),
                avg_latency_ms=Avg("latency_ms"),
            )
            .order_by("-total_cost_usd")
        ):
            by_model.append(
                {
                    "model": row["model"],
                    "total_calls": row["total_calls"],
                    "total_cost_usd": str(row["total_cost_usd"] or Decimal("0")),
                    "avg_latency_ms": (
                        round(row["avg_latency_ms"], 1) if row["avg_latency_ms"] else None
                    ),
                }
            )

        # By-day breakdown.
        by_day: list[dict] = []
        for row in (
            qs.annotate(date=TruncDate("timestamp"))
            .values("date")
            .annotate(
                total_calls=Count("id"),
                total_cost_usd=Sum("cost_usd"),
                avg_latency_ms=Avg("latency_ms"),
            )
            .order_by("-date")
        ):
            by_day.append(
                {
                    "date": row["date"].isoformat() if row["date"] else None,
                    "total_calls": row["total_calls"],
                    "total_cost_usd": str(row["total_cost_usd"] or Decimal("0")),
                    "avg_latency_ms": (
                        round(row["avg_latency_ms"], 1) if row["avg_latency_ms"] else None
                    ),
                }
            )

        # --- Live today from Redis cache (real-time, no DB query needed) ---
        live_today = self._get_live_today_costs()

        payload = {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "totals": {
                "total_calls": totals_agg["total_calls"] or 0,
                "total_cost_usd": str(totals_agg["total_cost_usd"] or Decimal("0")),
                "avg_latency_ms": (
                    round(totals_agg["avg_latency_ms"], 1)
                    if totals_agg["avg_latency_ms"]
                    else None
                ),
                "by_action": action_counts,
            },
            "by_model": by_model,
            "by_day": by_day,
            "live_today": live_today,
        }

        return Response(payload, status=status.HTTP_200_OK)

    @staticmethod
    def _get_live_today_costs() -> dict:
        """
        Read today's real-time cost from Redis without a database query.

        Falls back gracefully if Redis is unavailable or the keys don't exist.
        """
        from django.conf import settings

        today = timezone.now().date().isoformat()
        scout_model: str = getattr(settings, "SCOUT_MODEL", "")
        confirmer_model: str = getattr(settings, "CONFIRMER_MODEL", "")

        def _safe_get_cost(model: str) -> float:
            try:
                key = f"{CACHE_PREFIX_DAILY_COST}{model}:{today}"
                return float(cache.get(key) or 0.0)
            except Exception:  # noqa: BLE001
                return 0.0

        def _safe_get_calls(model: str) -> int:
            try:
                key = f"{CACHE_PREFIX_DAILY_CALLS}{model}:{today}"
                return int(cache.get(key) or 0)
            except Exception:  # noqa: BLE001
                return 0

        return {
            "scout_model": scout_model,
            "scout_calls": _safe_get_calls(scout_model),
            "scout_cost_usd": round(_safe_get_cost(scout_model), 6),
            "confirmer_model": confirmer_model,
            "confirmer_calls": _safe_get_calls(confirmer_model),
            "confirmer_cost_usd": round(_safe_get_cost(confirmer_model), 6),
        }
