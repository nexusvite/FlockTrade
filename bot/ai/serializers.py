"""
DRF serializers for the AI app.

Provides:
  - AIDecisionSerializer: Full read serializer for AIDecision records.
  - AIDecisionListSerializer: Lightweight version for paginated list views.
  - AICostSerializer: Serializer for the cost breakdown response.
  - AICostQuerySerializer: Input validation for cost filter parameters.
"""
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from .models import AIAction, AIDecision, AIRole


class AIDecisionListSerializer(serializers.ModelSerializer):
    """
    Compact serializer for paginated list views.

    Omits heavy text fields (input_context, raw_response) to reduce payload
    size when listing thousands of decisions.
    """

    role_display = serializers.CharField(source="get_role_display", read_only=True)
    action_display = serializers.CharField(source="get_action_display", read_only=True)
    is_actionable = serializers.BooleanField(read_only=True)

    class Meta:
        model = AIDecision
        fields = [
            "id",
            "timestamp",
            "symbol",
            "role",
            "role_display",
            "model",
            "action",
            "action_display",
            "confidence",
            "reason",
            "latency_ms",
            "cost_usd",
            "is_actionable",
        ]
        read_only_fields = fields


class AIDecisionSerializer(AIDecisionListSerializer):
    """
    Full serializer for the detail view.

    Includes the full input_context and raw_response fields for debugging
    and AI accuracy analysis.
    """

    cost_display = serializers.SerializerMethodField()

    class Meta(AIDecisionListSerializer.Meta):
        fields = AIDecisionListSerializer.Meta.fields + [
            "input_context",
            "raw_response",
            "cost_display",
        ]
        read_only_fields = fields

    def get_cost_display(self, obj: AIDecision) -> str:
        return obj.cost_display


# ---------------------------------------------------------------------------
# Cost breakdown serializers
# ---------------------------------------------------------------------------


class DailyModelCostSerializer(serializers.Serializer):
    """
    Serializes a single model's cost entry for a given day.
    Used in the nested list inside AICostSerializer.
    """

    model = serializers.CharField()
    date = serializers.DateField()
    total_calls = serializers.IntegerField(min_value=0)
    total_cost_usd = serializers.DecimalField(max_digits=10, decimal_places=6)
    avg_latency_ms = serializers.FloatField(allow_null=True, required=False)
    avg_cost_per_call = serializers.DecimalField(
        max_digits=10, decimal_places=8, required=False
    )


class AICostSerializer(serializers.Serializer):
    """
    Serializes the aggregated cost breakdown response from AICostView.

    Response structure:
    {
        "period": {"start": "2026-03-01", "end": "2026-03-18"},
        "totals": {"total_calls": 145, "total_cost_usd": "0.023400"},
        "by_model": [...],       # grouped by model
        "by_day": [...]          # grouped by day
    }
    """

    period = serializers.DictField(child=serializers.DateField())
    totals = serializers.DictField()
    by_model = serializers.ListField(child=DailyModelCostSerializer())
    by_day = serializers.ListField(child=DailyModelCostSerializer())


class AICostQuerySerializer(serializers.Serializer):
    """
    Input validation serializer for query parameters on AICostView.

    GET /api/ai/costs/?start=2026-03-01&end=2026-03-18&model=anthropic/...
    """

    start = serializers.DateField(
        required=False,
        default=None,
        help_text="Start date (inclusive). Defaults to 30 days ago.",
    )
    end = serializers.DateField(
        required=False,
        default=None,
        help_text="End date (inclusive). Defaults to today.",
    )
    model = serializers.CharField(
        required=False,
        default=None,
        max_length=100,
        help_text="Filter by specific model identifier.",
    )

    def validate(self, attrs: dict) -> dict:
        today = timezone.now().date()

        if attrs.get("start") is None:
            attrs["start"] = today.replace(day=1)  # First of current month

        if attrs.get("end") is None:
            attrs["end"] = today

        if attrs["start"] > attrs["end"]:
            raise serializers.ValidationError(
                {"end": "End date must be on or after start date."}
            )

        return attrs


class AIDecisionFilterSerializer(serializers.Serializer):
    """
    Input validation for AIDecisionListView query parameters.

    GET /api/ai/decisions/?symbol=USDJPYm&role=scout&action=BUY&page=2
    """

    symbol = serializers.CharField(
        required=False,
        max_length=20,
        help_text="Filter by trading pair symbol.",
    )
    role = serializers.ChoiceField(
        choices=AIRole.choices,
        required=False,
        help_text="Filter by AI role: scout, confirmer, or exit.",
    )
    action = serializers.ChoiceField(
        choices=AIAction.choices,
        required=False,
        help_text="Filter by AI action.",
    )
    model = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Filter by model name.",
    )
    min_confidence = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=100,
        help_text="Only return decisions with confidence >= this value.",
    )
    date = serializers.DateField(
        required=False,
        help_text="Filter by date (UTC). Returns all decisions for that day.",
    )
