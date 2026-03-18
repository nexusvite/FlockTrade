"""
AI Decision model for FlockTrade.

Logs every scout and confirmer AI call with full context, response,
latency, and cost for auditing, analysis, and cost tracking.
"""
import uuid

from django.db import models
from django.utils import timezone


class AIRole(models.TextChoices):
    SCOUT = "scout", "Scout"
    CONFIRMER = "confirmer", "Confirmer"
    EXIT = "exit", "Exit Manager"


class AIAction(models.TextChoices):
    BUY = "BUY", "Buy"
    SELL = "SELL", "Sell"
    SKIP = "SKIP", "Skip"
    CONFIRM = "CONFIRM", "Confirm"
    REJECT = "REJECT", "Reject"
    HOLD = "HOLD", "Hold"
    CLOSE = "CLOSE", "Close"
    ERROR = "ERROR", "Error"


class AIDecisionManager(models.Manager):
    """Custom manager with convenience querysets."""

    def for_symbol(self, symbol: str):
        return self.filter(symbol=symbol)

    def for_role(self, role: str):
        return self.filter(role=role)

    def today(self):
        today = timezone.now().date()
        return self.filter(timestamp__date=today)

    def daily_cost_summary(self):
        """Aggregate cost and call count per model per date."""
        from django.db.models import Count, Sum
        from django.db.models.functions import TruncDate

        return (
            self.annotate(date=TruncDate("timestamp"))
            .values("date", "model", "role")
            .annotate(
                total_calls=Count("id"),
                total_cost=Sum("cost_usd"),
                avg_latency_ms=models.Avg("latency_ms"),
            )
            .order_by("-date", "model")
        )


class AIDecision(models.Model):
    """
    Immutable audit record of every AI call made by the trading engine.

    Each record captures the full input, raw response, parsed result,
    timing, and cost so we can replay, debug, and analyse AI accuracy
    over time without re-calling the API.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_comment="Unique decision identifier (UUID v4)",
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        db_comment="UTC time the API call was initiated",
    )
    symbol = models.CharField(
        max_length=20,
        db_index=True,
        db_comment="Forex pair / instrument, e.g. USDJPYm",
    )
    role = models.CharField(
        max_length=10,
        choices=AIRole.choices,
        db_index=True,
        db_comment="Which AI agent made this call",
    )
    model = models.CharField(
        max_length=100,
        db_comment="Full OpenRouter model identifier, e.g. anthropic/claude-haiku-4.5",
    )
    action = models.CharField(
        max_length=10,
        choices=AIAction.choices,
        db_index=True,
        db_comment="Parsed action from AI response",
    )
    confidence = models.IntegerField(
        db_comment="AI-reported confidence 0-100",
    )
    reason = models.TextField(
        db_comment="Plain-English reason extracted from AI response",
    )
    input_context = models.TextField(
        db_comment="Full serialised context dict sent to the AI (JSON string)",
    )
    raw_response = models.TextField(
        db_comment="Raw text body returned by the OpenRouter API",
    )
    latency_ms = models.IntegerField(
        db_comment="Round-trip API latency in milliseconds",
    )
    cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        db_comment="Estimated USD cost for this single API call",
    )

    objects = AIDecisionManager()

    class Meta:
        db_table = "ai_decisions"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["symbol", "role", "-timestamp"]),
            models.Index(fields=["model", "-timestamp"]),
            # Partial index: only action decisions (non-SKIP/ERROR) for fast
            # accuracy queries — uses PostgreSQL partial-index syntax.
            models.Index(
                fields=["symbol", "action"],
                name="ai_decisions_active_idx",
                condition=models.Q(action__in=["BUY", "SELL", "CONFIRM"]),
            ),
        ]
        verbose_name = "AI Decision"
        verbose_name_plural = "AI Decisions"

    def __str__(self) -> str:
        return (
            f"[{self.role.upper()}] {self.symbol} → {self.action} "
            f"({self.confidence}%) @ {self.timestamp:%Y-%m-%d %H:%M:%S}"
        )

    @property
    def is_actionable(self) -> bool:
        """True if the AI recommended an actual trade action (not skip/hold)."""
        return self.action in {AIAction.BUY, AIAction.SELL, AIAction.CONFIRM}

    @property
    def cost_display(self) -> str:
        """Human-readable cost string."""
        return f"${self.cost_usd:.6f}"
