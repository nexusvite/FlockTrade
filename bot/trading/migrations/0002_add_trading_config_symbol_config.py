# Generated manually for FlockTrade

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("trading", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TradingConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mt5_broker", models.CharField(blank=True, default="custom", help_text="Broker preset: exness, ftmo, custom", max_length=50)),
                ("mt5_account", models.CharField(blank=True, default="", max_length=50)),
                ("mt5_password", models.CharField(blank=True, default="", max_length=200)),
                ("mt5_server", models.CharField(blank=True, default="", max_length=100)),
                ("mt5_host", models.CharField(blank=True, default="mt5-trading", max_length=100)),
                ("mt5_port", models.IntegerField(default=8001)),
                ("openrouter_api_key", models.CharField(blank=True, default="", max_length=200)),
                ("scout_model", models.CharField(default="anthropic/claude-haiku-4.5", max_length=100)),
                ("confirmer_model", models.CharField(default="anthropic/claude-sonnet-4-6", max_length=100)),
                ("ai_timeout", models.IntegerField(default=15)),
                ("max_daily_losses", models.IntegerField(default=3)),
                ("max_daily_loss_usd", models.DecimalField(decimal_places=2, default=100, max_digits=10)),
                ("asia_start", models.IntegerField(default=1)),
                ("asia_end", models.IntegerField(default=6)),
                ("london_start", models.IntegerField(default=8)),
                ("london_end", models.IntegerField(default=12)),
                ("ny_start", models.IntegerField(default=13)),
                ("ny_end", models.IntegerField(default=20)),
                ("lot_size_forex", models.DecimalField(decimal_places=2, default=1.0, max_digits=8)),
                ("lot_size_gold", models.DecimalField(decimal_places=2, default=0.1, max_digits=8)),
                ("tp_pips_forex", models.IntegerField(default=2)),
                ("sl_pips_forex", models.IntegerField(default=5)),
                ("tp_pips_gold", models.IntegerField(default=20)),
                ("sl_pips_gold", models.IntegerField(default=50)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "trading_config",
                "verbose_name": "Trading Config",
                "verbose_name_plural": "Trading Config",
            },
        ),
        migrations.CreateModel(
            name="SymbolConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("symbol", models.CharField(max_length=20, unique=True)),
                ("enabled", models.BooleanField(default=True)),
                ("lot_size", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("tp_pips", models.IntegerField(blank=True, null=True)),
                ("sl_pips", models.IntegerField(blank=True, null=True)),
                ("max_spread_pips", models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "symbol_config",
                "ordering": ["symbol"],
            },
        ),
    ]
