"""
Trading models for FlockTrade.

Defines the core database models for trade history, support/resistance
levels, daily performance statistics, and bot status tracking.
"""
import uuid
from django.db import models
from django.utils import timezone


class Trade(models.Model):
    """
    Represents a single completed or open forex trade.

    Stores full context including entry/exit prices, AI decisions,
    filter results, and level metadata for post-trade analysis.
    """

    class TradeType(models.TextChoices):
        BUY = "BUY", "Buy"
        SELL = "SELL", "Sell"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    symbol = models.CharField(max_length=20, db_index=True)
    type = models.CharField(max_length=4, choices=TradeType.choices)

    # Price levels
    entry_price = models.DecimalField(max_digits=12, decimal_places=5, null=True, blank=True)
    exit_price = models.DecimalField(max_digits=12, decimal_places=5, null=True, blank=True)
    sl = models.DecimalField(max_digits=12, decimal_places=5, null=True, blank=True)
    tp = models.DecimalField(max_digits=12, decimal_places=5, null=True, blank=True)
    lot_size = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    # Financial result
    pnl = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, db_index=True)

    # Timing
    entry_time = models.DateTimeField(null=True, blank=True, db_index=True)
    exit_time = models.DateTimeField(null=True, blank=True)
    bars_held = models.IntegerField(null=True, blank=True)

    # S/R level metadata at time of entry
    level_price = models.DecimalField(max_digits=12, decimal_places=5, null=True, blank=True)
    level_strength = models.IntegerField(null=True, blank=True)
    level_timeframes = models.CharField(max_length=200, blank=True, default="")

    # AI Scout decision
    scout_action = models.CharField(max_length=10, blank=True, default="")
    scout_confidence = models.IntegerField(null=True, blank=True)
    scout_reason = models.TextField(blank=True, default="")

    # AI Confirmer decision
    confirmer_action = models.CharField(max_length=10, blank=True, default="")
    confirmer_confidence = models.IntegerField(null=True, blank=True)
    confirmer_reason = models.TextField(blank=True, default="")

    # Exit metadata
    exit_reason = models.TextField(blank=True, default="")

    # Full filter chain log stored as JSON
    # Example: {"session_filter": "PASS", "spread_filter": "PASS", ...}
    filters_log = models.JSONField(default=dict, blank=True)

    # Record timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "trades"
        ordering = ["-entry_time"]
        indexes = [
            models.Index(fields=["symbol", "entry_time"]),
            models.Index(fields=["pnl"]),
            models.Index(fields=["entry_time"]),
        ]

    def __str__(self) -> str:
        return f"{self.symbol} {self.type} @ {self.entry_price} ({self.entry_time})"

    @property
    def is_open(self) -> bool:
        """Trade is open if it has no exit time."""
        return self.exit_time is None

    @property
    def is_win(self) -> bool:
        """Win if PnL is positive and trade is closed."""
        return self.pnl is not None and self.pnl > 0

    @property
    def is_loss(self) -> bool:
        """Loss if PnL is negative and trade is closed."""
        return self.pnl is not None and self.pnl < 0

    @property
    def is_scratch(self) -> bool:
        """Scratch if PnL is exactly zero and trade is closed."""
        return self.pnl is not None and self.pnl == 0


class SRLevel(models.Model):
    """
    Cached support/resistance level detected across multiple timeframes.

    Levels are detected each scan and merged across confluent price zones.
    Strength accumulates when multiple timeframes agree on the same price.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    symbol = models.CharField(max_length=20, db_index=True)
    price = models.DecimalField(max_digits=12, decimal_places=5)
    strength = models.IntegerField(default=1, db_index=True)

    # List of timeframe strings that agree on this level, e.g. ["H1", "M15"]
    timeframes = models.JSONField(default=list)

    # Session-level touch tracking (reset each trading day)
    session_touches = models.IntegerField(default=0)

    # Level lifecycle timestamps
    first_detected = models.DateTimeField(default=timezone.now)
    last_touched = models.DateTimeField(null=True, blank=True)

    # Whether the bot has already traded this level in the current session
    traded = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "sr_levels"
        ordering = ["-strength", "symbol"]
        indexes = [
            models.Index(fields=["symbol", "strength"]),
            models.Index(fields=["symbol", "price"]),
            models.Index(fields=["traded"]),
        ]

    def __str__(self) -> str:
        tf_str = ",".join(self.timeframes) if self.timeframes else ""
        return f"{self.symbol} S/R @ {self.price} str={self.strength} [{tf_str}]"


class DailyStats(models.Model):
    """
    Aggregated daily trading performance statistics.

    One row per calendar day. Updated at trade close and end-of-day.
    """

    date = models.DateField(primary_key=True)
    trades = models.IntegerField(default=0)
    wins = models.IntegerField(default=0)
    losses = models.IntegerField(default=0)
    scratches = models.IntegerField(default=0)

    # Financial aggregates
    pnl = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    ai_cost = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    # Best and worst single trade of the day
    best_trade = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    worst_trade = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "daily_stats"
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"DailyStats {self.date}: {self.wins}W/{self.losses}L PnL={self.pnl}"

    @property
    def win_rate(self) -> float:
        """Win rate as a percentage. Returns 0 if no trades taken."""
        if self.trades == 0:
            return 0.0
        return round((self.wins / self.trades) * 100, 2)

    @classmethod
    def get_today(cls) -> "DailyStats":
        """Get or create today's stats row."""
        stats, _ = cls.objects.get_or_create(date=timezone.now().date())
        return stats


class BotStatusManager(models.Manager):
    """Manager that enforces singleton semantics for BotStatus."""

    def get_status(self) -> "BotStatus":
        """Return the singleton BotStatus row, creating it if absent."""
        status, _ = self.get_or_create(pk=1)
        return status


class BotStatus(models.Model):
    """
    Singleton model representing the current state of the trading bot.

    Only one row should ever exist (pk=1). Use BotStatus.objects.get_status()
    to safely access or create it.
    """

    # Bot state flags
    is_running = models.BooleanField(default=False)
    is_paused = models.BooleanField(default=False)

    # MT5 connectivity
    connected_to_mt5 = models.BooleanField(default=False)
    last_scan_time = models.DateTimeField(null=True, blank=True)
    last_health_check = models.DateTimeField(null=True, blank=True)

    # Account snapshot (updated each scan)
    account_balance = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    account_equity = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    # Daily circuit-breaker counters
    daily_losses = models.IntegerField(default=0)
    daily_loss_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Last error message for dashboard display
    last_error = models.TextField(blank=True, default="")

    updated_at = models.DateTimeField(auto_now=True)

    objects = BotStatusManager()

    class Meta:
        db_table = "bot_status"
        verbose_name = "Bot Status"
        verbose_name_plural = "Bot Status"

    def __str__(self) -> str:
        state = "RUNNING" if self.is_running else "STOPPED"
        if self.is_paused:
            state = "PAUSED"
        mt5 = "MT5:OK" if self.connected_to_mt5 else "MT5:DISCONNECTED"
        return f"BotStatus [{state}] [{mt5}] balance={self.account_balance}"

    def save(self, *args, **kwargs) -> None:
        """Force singleton by always using pk=1."""
        self.pk = 1
        super().save(*args, **kwargs)

    @property
    def is_circuit_breaker_triggered(self) -> bool:
        """
        Returns True if daily loss limit has been hit.

        Reads thresholds from Django settings so they can be configured
        without code changes.
        """
        from django.conf import settings

        max_losses = getattr(settings, "MAX_DAILY_LOSSES", 3)
        max_loss_usd = getattr(settings, "MAX_DAILY_LOSS_USD", 100)

        return self.daily_losses >= max_losses or float(self.daily_loss_usd) >= max_loss_usd

    def mark_connected(self, balance: float, equity: float) -> None:
        """Update MT5 connection state and account snapshot."""
        self.connected_to_mt5 = True
        self.account_balance = balance
        self.account_equity = equity
        self.last_health_check = timezone.now()
        self.last_error = ""
        self.save()

    def mark_disconnected(self, error: str = "") -> None:
        """Mark MT5 as disconnected and record the error message."""
        self.connected_to_mt5 = False
        self.last_error = error
        self.last_health_check = timezone.now()
        self.save()
