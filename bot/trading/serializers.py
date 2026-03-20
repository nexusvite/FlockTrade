"""
DRF Serializers for the Trading app.

Provides serialisation for Trade, SRLevel, DailyStats, and BotStatus
models. Includes read-only detail serializers and minimal write
serializers for the control/config endpoints.
"""
from __future__ import annotations

from rest_framework import serializers

from trading.models import BotStatus, DailyStats, SRLevel, SymbolConfig, Trade, TradingConfig


# ---------------------------------------------------------------------------
# Trade serializers
# ---------------------------------------------------------------------------


class TradeListSerializer(serializers.ModelSerializer):
    """
    Compact serializer used in paginated list responses.

    Excludes verbose AI reasoning fields to keep payload small.
    """

    is_open = serializers.BooleanField(read_only=True)
    win_loss = serializers.SerializerMethodField()

    class Meta:
        model = Trade
        fields = [
            "id",
            "symbol",
            "type",
            "account_type",
            "entry_price",
            "exit_price",
            "sl",
            "tp",
            "lot_size",
            "pnl",
            "entry_time",
            "exit_time",
            "bars_held",
            "level_price",
            "level_strength",
            "is_open",
            "win_loss",
        ]
        read_only_fields = fields

    def get_win_loss(self, obj: Trade) -> str | None:
        """Return a human-readable outcome label."""
        if obj.is_open:
            return "OPEN"
        if obj.is_win:
            return "WIN"
        if obj.is_loss:
            return "LOSS"
        if obj.is_scratch:
            return "SCRATCH"
        return None


class TradeDetailSerializer(serializers.ModelSerializer):
    """
    Full trade detail including AI reasoning and filter chain log.
    """

    is_open = serializers.BooleanField(read_only=True)
    win_loss = serializers.SerializerMethodField()
    level_timeframes_list = serializers.SerializerMethodField()

    class Meta:
        model = Trade
        fields = [
            "id",
            "symbol",
            "type",
            "account_type",
            "binance_order_id",
            "entry_price",
            "exit_price",
            "sl",
            "tp",
            "lot_size",
            "pnl",
            "entry_time",
            "exit_time",
            "bars_held",
            "level_price",
            "level_strength",
            "level_timeframes",
            "level_timeframes_list",
            "scout_action",
            "scout_confidence",
            "scout_reason",
            "confirmer_action",
            "confirmer_confidence",
            "confirmer_reason",
            "exit_reason",
            "filters_log",
            "is_open",
            "win_loss",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_win_loss(self, obj: Trade) -> str | None:
        if obj.is_open:
            return "OPEN"
        if obj.is_win:
            return "WIN"
        if obj.is_loss:
            return "LOSS"
        if obj.is_scratch:
            return "SCRATCH"
        return None

    def get_level_timeframes_list(self, obj: Trade) -> list[str]:
        """Return level_timeframes as a list for easier frontend consumption."""
        if not obj.level_timeframes:
            return []
        return [tf.strip() for tf in obj.level_timeframes.split(",") if tf.strip()]


# ---------------------------------------------------------------------------
# SRLevel serializers
# ---------------------------------------------------------------------------


class SRLevelSerializer(serializers.ModelSerializer):
    """Serializer for S/R levels with computed distance field."""

    current_price = serializers.SerializerMethodField()
    distance_pips = serializers.SerializerMethodField()

    class Meta:
        model = SRLevel
        fields = [
            "id",
            "symbol",
            "price",
            "strength",
            "timeframes",
            "session_touches",
            "first_detected",
            "last_touched",
            "traded",
            "distance_pips",
            "current_price",
        ]
        read_only_fields = fields

    def get_current_price(self, obj: SRLevel) -> float | None:
        """
        Optionally inject current price from the view context.

        Views that know the current price can pass it via context:
            serializer = SRLevelSerializer(
                queryset, many=True,
                context={"current_prices": {"USDJPYm": 155.432}}
            )
        """
        prices = self.context.get("current_prices", {})
        return prices.get(obj.symbol)

    def get_distance_pips(self, obj: SRLevel) -> float | None:
        """Distance from current price in pips, if current_price is available."""
        from trading.instrument import get_pip_size

        prices = self.context.get("current_prices", {})
        current_price = prices.get(obj.symbol)
        if current_price is None:
            return None

        pip_size = get_pip_size(obj.symbol)
        if pip_size == 0:
            return None

        return round(abs(float(obj.price) - current_price) / pip_size, 1)


# ---------------------------------------------------------------------------
# DailyStats serializer
# ---------------------------------------------------------------------------


class DailyStatsSerializer(serializers.ModelSerializer):
    """Serializer for daily performance statistics."""

    win_rate = serializers.FloatField(read_only=True)

    class Meta:
        model = DailyStats
        fields = [
            "date",
            "trades",
            "wins",
            "losses",
            "scratches",
            "pnl",
            "ai_cost",
            "best_trade",
            "worst_trade",
            "win_rate",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# BotStatus serializers
# ---------------------------------------------------------------------------


class BotStatusSerializer(serializers.ModelSerializer):
    """Read-only serializer for the bot's current status."""

    circuit_breaker_active = serializers.BooleanField(
        source="is_circuit_breaker_triggered", read_only=True
    )
    state = serializers.SerializerMethodField()

    class Meta:
        model = BotStatus
        fields = [
            "account_type",
            "is_running",
            "is_paused",
            "connected_to_exchange",
            "last_scan_time",
            "last_health_check",
            "account_balance",
            "account_equity",
            "daily_losses",
            "daily_loss_usd",
            "last_error",
            "circuit_breaker_active",
            "state",
            "updated_at",
        ]
        read_only_fields = fields

    def get_state(self, obj: BotStatus) -> str:
        """Human-readable bot state string."""
        if not obj.is_running:
            return "STOPPED"
        if obj.is_paused:
            return "PAUSED"
        if obj.is_circuit_breaker_triggered:
            return "CIRCUIT_BREAKER"
        if not obj.connected_to_exchange:
            return "DISCONNECTED"
        return "RUNNING"


class BotControlSerializer(serializers.Serializer):
    """
    Write serializer for the pause/resume control endpoint.

    Validates the requested action before the view processes it.
    """

    action = serializers.ChoiceField(choices=["pause", "resume", "stop", "start"])


# ---------------------------------------------------------------------------
# Performance serializer (aggregated, not a model)
# ---------------------------------------------------------------------------


class PerformanceSerializer(serializers.Serializer):
    """
    Aggregated performance statistics returned by PerformanceView.

    Not bound to a model — populated from annotated querysets.
    """

    period = serializers.CharField(read_only=True)      # e.g. "today", "7d", "30d"
    total_trades = serializers.IntegerField(read_only=True)
    wins = serializers.IntegerField(read_only=True)
    losses = serializers.IntegerField(read_only=True)
    scratches = serializers.IntegerField(read_only=True)
    win_rate = serializers.FloatField(read_only=True)
    total_pnl = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    avg_pnl_per_trade = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    best_trade = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    worst_trade = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    avg_bars_held = serializers.FloatField(read_only=True)

    # Per-symbol breakdown
    by_symbol = serializers.ListField(child=serializers.DictField(), read_only=True)

    # Per-level-strength breakdown
    by_strength = serializers.ListField(child=serializers.DictField(), read_only=True)


# ---------------------------------------------------------------------------
# Config update serializer
# ---------------------------------------------------------------------------


class ConfigUpdateSerializer(serializers.Serializer):
    """Legacy serializer kept for backwards compatibility."""

    symbols = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False, min_length=1, max_length=10,
    )
    lot_size_forex = serializers.FloatField(required=False, min_value=0.01, max_value=100.0)
    lot_size_gold = serializers.FloatField(required=False, min_value=0.01, max_value=10.0)
    tp_pips_forex = serializers.IntegerField(required=False, min_value=1, max_value=50)
    sl_pips_forex = serializers.IntegerField(required=False, min_value=1, max_value=100)
    tp_pips_gold = serializers.IntegerField(required=False, min_value=5, max_value=200)
    sl_pips_gold = serializers.IntegerField(required=False, min_value=5, max_value=500)
    max_daily_losses = serializers.IntegerField(required=False, min_value=1, max_value=20)
    max_daily_loss_usd = serializers.FloatField(required=False, min_value=10.0, max_value=10000.0)
    scout_model = serializers.CharField(max_length=100, required=False)
    confirmer_model = serializers.CharField(max_length=100, required=False)


# ---------------------------------------------------------------------------
# TradingConfig serializers (DB-backed global config)
# ---------------------------------------------------------------------------


class TradingConfigReadSerializer(serializers.ModelSerializer):
    """Read serializer that masks secrets."""

    mt5_password = serializers.SerializerMethodField()
    openrouter_api_key = serializers.SerializerMethodField()

    class Meta:
        model = TradingConfig
        exclude = ["id"]
        read_only_fields = ["updated_at"]

    def get_mt5_password(self, obj: TradingConfig) -> str:
        if obj.mt5_password:
            return "••••" + obj.mt5_password[-4:] if len(obj.mt5_password) > 4 else "••••"
        return ""

    def get_openrouter_api_key(self, obj: TradingConfig) -> str:
        if obj.openrouter_api_key:
            return "sk-••••" + obj.openrouter_api_key[-4:] if len(obj.openrouter_api_key) > 4 else "••••"
        return ""


class TradingConfigUpdateSerializer(serializers.ModelSerializer):
    """Write serializer — all fields optional for partial updates."""

    class Meta:
        model = TradingConfig
        exclude = ["id", "updated_at"]
        extra_kwargs = {f.name: {"required": False} for f in TradingConfig._meta.get_fields() if hasattr(f, "name")}


# ---------------------------------------------------------------------------
# SymbolConfig serializer
# ---------------------------------------------------------------------------


class SymbolConfigSerializer(serializers.ModelSerializer):
    """Full CRUD serializer for per-symbol configuration."""

    instrument_type = serializers.SerializerMethodField()

    class Meta:
        model = SymbolConfig
        fields = [
            "id", "symbol", "enabled", "lot_size", "tp_pips",
            "sl_pips", "max_spread_pips", "instrument_type",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "instrument_type", "created_at", "updated_at"]

    def get_instrument_type(self, obj: SymbolConfig) -> str:
        from trading.instrument import detect_instrument
        return detect_instrument(obj.symbol).value
