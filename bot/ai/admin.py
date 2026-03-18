"""
Django Admin registration for the AI app.

Provides a rich admin interface for:
  - AIDecision: Full audit trail of all AI calls, filterable by role, action,
    symbol, model, and date. Includes a read-only detail view with full context.

Design decisions:
  - All fields are read-only — decisions are immutable audit records.
  - List display shows the most actionable columns at a glance.
  - Colour-coded action column via a custom display method.
  - Cost and latency displayed in human-readable format.
  - raw_response and input_context are shown in monospace for readability.
"""
from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import AIDecision

# Colour mapping for action field badges.
_ACTION_COLOURS: dict[str, str] = {
    "BUY": "#28a745",       # Green
    "SELL": "#dc3545",      # Red
    "CONFIRM": "#28a745",   # Green
    "REJECT": "#dc3545",    # Red
    "SKIP": "#6c757d",      # Grey
    "HOLD": "#fd7e14",      # Orange
    "CLOSE": "#dc3545",     # Red
    "ERROR": "#6f42c1",     # Purple
}


@admin.register(AIDecision)
class AIDecisionAdmin(admin.ModelAdmin):
    """
    Admin view for AIDecision records.

    Provides comprehensive filtering, searching, and display of all AI
    decisions made by the trading engine. All records are read-only.
    """

    # --- List view ---
    list_display = [
        "timestamp",
        "symbol",
        "role_badge",
        "action_badge",
        "confidence",
        "model_short",
        "latency_display",
        "cost_display",
        "reason_short",
    ]
    list_filter = [
        "role",
        "action",
        "symbol",
        ("timestamp", admin.DateFieldListFilter),
    ]
    search_fields = ["symbol", "reason", "model", "raw_response"]
    ordering = ["-timestamp"]
    date_hierarchy = "timestamp"

    # --- Detail view ---
    readonly_fields = [
        "id",
        "timestamp",
        "symbol",
        "role",
        "model",
        "action",
        "confidence",
        "reason",
        "latency_ms",
        "cost_usd",
        "input_context_formatted",
        "raw_response_formatted",
    ]

    fieldsets = [
        (
            "Decision Summary",
            {
                "fields": [
                    ("id", "timestamp"),
                    ("symbol", "role", "model"),
                    ("action", "confidence"),
                    "reason",
                ]
            },
        ),
        (
            "Performance",
            {
                "fields": [("latency_ms", "cost_usd")],
                "classes": ["collapse"],
            },
        ),
        (
            "Input Context (sent to AI)",
            {
                "fields": ["input_context_formatted"],
                "classes": ["collapse"],
                "description": (
                    "Full JSON context dict that was sent to the AI model. "
                    "Contains candles, S/R levels, indicators."
                ),
            },
        ),
        (
            "Raw AI Response",
            {
                "fields": ["raw_response_formatted"],
                "classes": ["collapse"],
                "description": (
                    "Raw text returned by the OpenRouter API before parsing."
                ),
            },
        ),
    ]

    # --- Disable add / change / delete (read-only admin) ---
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        # Allow superusers to delete for data hygiene (e.g. purge old records).
        return request.user.is_superuser

    # --- Custom display methods ---

    @admin.display(description="Role", ordering="role")
    def role_badge(self, obj: AIDecision) -> str:
        colour_map = {
            "scout": "#0d6efd",
            "confirmer": "#fd7e14",
            "exit": "#6f42c1",
        }
        colour = colour_map.get(obj.role, "#6c757d")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;font-weight:bold;">{}</span>',
            colour,
            obj.get_role_display(),
        )

    @admin.display(description="Action", ordering="action")
    def action_badge(self, obj: AIDecision) -> str:
        colour = _ACTION_COLOURS.get(obj.action, "#6c757d")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;font-weight:bold;">{}</span>',
            colour,
            obj.action,
        )

    @admin.display(description="Model", ordering="model")
    def model_short(self, obj: AIDecision) -> str:
        """Show only the model name part (after the provider prefix)."""
        parts = obj.model.split("/")
        return parts[-1] if len(parts) > 1 else obj.model

    @admin.display(description="Latency", ordering="latency_ms")
    def latency_display(self, obj: AIDecision) -> str:
        if obj.latency_ms == 0:
            return format_html('<span style="color:#6c757d;">cached</span>')
        colour = "#28a745" if obj.latency_ms < 2000 else "#dc3545"
        return format_html(
            '<span style="color:{};">{}ms</span>',
            colour,
            obj.latency_ms,
        )

    @admin.display(description="Cost", ordering="cost_usd")
    def cost_display(self, obj: AIDecision) -> str:
        if obj.cost_usd == 0:
            return format_html('<span style="color:#6c757d;">$0 (cached)</span>')
        return format_html(
            '<span style="font-family:monospace;">{}</span>',
            obj.cost_display,
        )

    @admin.display(description="Reason")
    def reason_short(self, obj: AIDecision) -> str:
        """Truncate reason for list display."""
        if len(obj.reason) > 80:
            return obj.reason[:77] + "..."
        return obj.reason

    @admin.display(description="Input Context")
    def input_context_formatted(self, obj: AIDecision) -> str:
        """Render input_context in a scrollable monospace block."""
        return format_html(
            '<pre style="max-height:400px;overflow:auto;background:#f8f9fa;'
            'padding:12px;border-radius:4px;font-size:12px;">{}</pre>',
            obj.input_context,
        )

    @admin.display(description="Raw AI Response")
    def raw_response_formatted(self, obj: AIDecision) -> str:
        """Render raw_response in a scrollable monospace block."""
        return format_html(
            '<pre style="max-height:300px;overflow:auto;background:#f8f9fa;'
            'padding:12px;border-radius:4px;font-size:12px;">{}</pre>',
            obj.raw_response,
        )
