"""
Django Admin configuration for the Trading app.

Provides rich admin interfaces for Trade, SRLevel, DailyStats,
and BotStatus with filtering, search, and inline display.
"""
from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html
from django.utils.safestring import SafeString

from trading.models import BotStatus, DailyStats, SRLevel, Trade


# ---------------------------------------------------------------------------
# Trade admin
# ---------------------------------------------------------------------------


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    """
    Admin interface for Trade history.

    Provides colour-coded P&L display and full filter/search capability.
    """

    list_display = [
        "id_short",
        "symbol",
        "type",
        "entry_price",
        "exit_price",
        "pnl_coloured",
        "level_strength",
        "scout_action",
        "confirmer_action",
        "entry_time",
        "exit_time",
        "bars_held",
        "is_open_badge",
    ]
    list_filter = [
        "symbol",
        "type",
        "scout_action",
        "confirmer_action",
        ("entry_time", admin.DateFieldListFilter),
    ]
    search_fields = [
        "symbol",
        "scout_reason",
        "confirmer_reason",
        "exit_reason",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "filters_log_pretty",
    ]
    ordering = ["-entry_time"]
    date_hierarchy = "entry_time"

    fieldsets = (
        (
            "Trade Info",
            {
                "fields": (
                    "id",
                    "symbol",
                    "type",
                    "lot_size",
                    "entry_price",
                    "exit_price",
                    "sl",
                    "tp",
                    "pnl",
                    "entry_time",
                    "exit_time",
                    "bars_held",
                    "exit_reason",
                )
            },
        ),
        (
            "S/R Level",
            {
                "fields": (
                    "level_price",
                    "level_strength",
                    "level_timeframes",
                )
            },
        ),
        (
            "AI Scout",
            {
                "fields": (
                    "scout_action",
                    "scout_confidence",
                    "scout_reason",
                )
            },
        ),
        (
            "AI Confirmer",
            {
                "fields": (
                    "confirmer_action",
                    "confirmer_confidence",
                    "confirmer_reason",
                )
            },
        ),
        (
            "Filter Log",
            {
                "fields": ("filters_log_pretty",),
                "classes": ("collapse",),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def id_short(self, obj: Trade) -> str:
        """Display first 8 chars of UUID for brevity."""
        return str(obj.id)[:8]

    id_short.short_description = "ID"  # type: ignore[attr-defined]

    def pnl_coloured(self, obj: Trade) -> SafeString:
        """Colour-coded P&L: green = profit, red = loss, grey = open/scratch."""
        if obj.pnl is None:
            return format_html('<span style="color: #aaa;">—</span>')
        if obj.pnl > 0:
            return format_html(
                '<span style="color: green; font-weight: bold;">+{}</span>', obj.pnl
            )
        if obj.pnl < 0:
            return format_html(
                '<span style="color: red; font-weight: bold;">{}</span>', obj.pnl
            )
        return format_html('<span style="color: #888;">0.00</span>')

    pnl_coloured.short_description = "P&L"  # type: ignore[attr-defined]
    pnl_coloured.admin_order_field = "pnl"  # type: ignore[attr-defined]

    def is_open_badge(self, obj: Trade) -> SafeString:
        """Display OPEN/CLOSED badge."""
        if obj.is_open:
            return format_html(
                '<span style="background: #2196F3; color: white; '
                'padding: 2px 8px; border-radius: 4px; font-size: 11px;">OPEN</span>'
            )
        return format_html(
            '<span style="background: #9E9E9E; color: white; '
            'padding: 2px 8px; border-radius: 4px; font-size: 11px;">CLOSED</span>'
        )

    is_open_badge.short_description = "Status"  # type: ignore[attr-defined]

    def filters_log_pretty(self, obj: Trade) -> SafeString:
        """Render filters_log as formatted JSON in the admin."""
        import json

        if not obj.filters_log:
            return format_html("<em>No filter data</em>")

        pretty = json.dumps(obj.filters_log, indent=2)
        return format_html("<pre style='font-size: 12px;'>{}</pre>", pretty)

    filters_log_pretty.short_description = "Filters Log (pretty)"  # type: ignore[attr-defined]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request).select_related()


# ---------------------------------------------------------------------------
# SRLevel admin
# ---------------------------------------------------------------------------


@admin.register(SRLevel)
class SRLevelAdmin(admin.ModelAdmin):
    """Admin interface for detected S/R levels."""

    list_display = [
        "symbol",
        "price",
        "strength_badge",
        "timeframes_display",
        "session_touches",
        "traded",
        "first_detected",
        "last_touched",
    ]
    list_filter = [
        "symbol",
        "traded",
        ("strength", admin.EmptyFieldListFilter),
    ]
    search_fields = ["symbol"]
    ordering = ["-strength", "symbol"]
    list_editable = ["traded"]

    def strength_badge(self, obj: SRLevel) -> SafeString:
        """Colour-coded strength badge."""
        strength = obj.strength
        if strength >= 7:
            colour = "#8B0000"   # dark red — very strong
        elif strength >= 5:
            colour = "#D32F2F"   # red — strong
        elif strength >= 3:
            colour = "#F57C00"   # orange — medium
        else:
            colour = "#1976D2"   # blue — weak

        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 12px; font-weight: bold;">{}</span>',
            colour,
            strength,
        )

    strength_badge.short_description = "Strength"  # type: ignore[attr-defined]
    strength_badge.admin_order_field = "strength"  # type: ignore[attr-defined]

    def timeframes_display(self, obj: SRLevel) -> str:
        """Join timeframes list for display."""
        if isinstance(obj.timeframes, list):
            return ", ".join(obj.timeframes)
        return str(obj.timeframes)

    timeframes_display.short_description = "Timeframes"  # type: ignore[attr-defined]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request)


# ---------------------------------------------------------------------------
# DailyStats admin
# ---------------------------------------------------------------------------


@admin.register(DailyStats)
class DailyStatsAdmin(admin.ModelAdmin):
    """Admin interface for daily performance statistics."""

    list_display = [
        "date",
        "trades",
        "wins",
        "losses",
        "scratches",
        "win_rate_display",
        "pnl_coloured",
        "ai_cost",
        "best_trade",
        "worst_trade",
    ]
    ordering = ["-date"]
    readonly_fields = ["win_rate_display"]

    def win_rate_display(self, obj: DailyStats) -> str:
        return f"{obj.win_rate}%"

    win_rate_display.short_description = "Win Rate"  # type: ignore[attr-defined]

    def pnl_coloured(self, obj: DailyStats) -> SafeString:
        if obj.pnl > 0:
            return format_html(
                '<span style="color: green; font-weight: bold;">+{}</span>', obj.pnl
            )
        if obj.pnl < 0:
            return format_html(
                '<span style="color: red; font-weight: bold;">{}</span>', obj.pnl
            )
        return format_html('<span>0.00</span>')

    pnl_coloured.short_description = "P&L"  # type: ignore[attr-defined]
    pnl_coloured.admin_order_field = "pnl"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# BotStatus admin
# ---------------------------------------------------------------------------


@admin.register(BotStatus)
class BotStatusAdmin(admin.ModelAdmin):
    """
    Admin interface for the singleton BotStatus.

    Provides an at-a-glance overview and allows manual control.
    Only one row should ever exist (pk=1).
    """

    list_display = [
        "state_badge",
        "connected_to_mt5_badge",
        "account_balance",
        "account_equity",
        "daily_losses",
        "daily_loss_usd",
        "last_scan_time",
        "last_health_check",
    ]
    readonly_fields = [
        "last_scan_time",
        "last_health_check",
        "updated_at",
        "state_badge",
        "connected_to_mt5_badge",
    ]

    fieldsets = (
        (
            "Bot State",
            {
                "fields": (
                    "state_badge",
                    "is_running",
                    "is_paused",
                )
            },
        ),
        (
            "MT5 Connection",
            {
                "fields": (
                    "connected_to_mt5_badge",
                    "connected_to_mt5",
                    "last_health_check",
                    "last_error",
                )
            },
        ),
        (
            "Account",
            {
                "fields": (
                    "account_balance",
                    "account_equity",
                )
            },
        ),
        (
            "Circuit Breaker",
            {
                "fields": (
                    "daily_losses",
                    "daily_loss_usd",
                )
            },
        ),
        (
            "Timing",
            {
                "fields": (
                    "last_scan_time",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def state_badge(self, obj: BotStatus) -> SafeString:
        """Colour-coded bot state badge."""
        if not obj.is_running:
            label, colour = "STOPPED", "#9E9E9E"
        elif obj.is_paused:
            label, colour = "PAUSED", "#FF9800"
        elif obj.is_circuit_breaker_triggered:
            label, colour = "CIRCUIT BREAKER", "#D32F2F"
        elif not obj.connected_to_mt5:
            label, colour = "DISCONNECTED", "#F44336"
        else:
            label, colour = "RUNNING", "#4CAF50"

        return format_html(
            '<span style="background: {}; color: white; padding: 4px 12px; '
            'border-radius: 4px; font-weight: bold;">{}</span>',
            colour,
            label,
        )

    state_badge.short_description = "State"  # type: ignore[attr-defined]

    def connected_to_mt5_badge(self, obj: BotStatus) -> SafeString:
        if obj.connected_to_mt5:
            return format_html(
                '<span style="color: green; font-weight: bold;">Connected</span>'
            )
        return format_html(
            '<span style="color: red; font-weight: bold;">Disconnected</span>'
        )

    connected_to_mt5_badge.short_description = "MT5"  # type: ignore[attr-defined]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent creating additional BotStatus rows (singleton)."""
        return not BotStatus.objects.exists()

    def has_delete_permission(
        self, request: HttpRequest, obj: BotStatus | None = None
    ) -> bool:
        """Prevent deletion of the singleton row."""
        return False
