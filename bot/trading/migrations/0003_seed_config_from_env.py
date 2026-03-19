"""
Data migration: seeds TradingConfig (pk=1) and SymbolConfig rows
from environment variables / Django settings.py defaults.
"""

import os
from django.db import migrations


def seed_config(apps, schema_editor):
    TradingConfig = apps.get_model("trading", "TradingConfig")
    SymbolConfig = apps.get_model("trading", "SymbolConfig")

    # Create singleton config row from env vars
    TradingConfig.objects.get_or_create(
        pk=1,
        defaults={
            "mt5_host": os.environ.get("MT5_HOST", "mt5-trading"),
            "mt5_port": int(os.environ.get("MT5_PORT", 8001)),
            "mt5_account": os.environ.get("MT5_ACCOUNT", ""),
            "mt5_password": os.environ.get("MT5_PASSWORD", ""),
            "mt5_server": os.environ.get("MT5_SERVER", ""),
            "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY", ""),
            "scout_model": os.environ.get("SCOUT_MODEL", "anthropic/claude-haiku-4.5"),
            "confirmer_model": os.environ.get("CONFIRMER_MODEL", "anthropic/claude-sonnet-4-6"),
            "ai_timeout": int(os.environ.get("AI_TIMEOUT", 15)),
            "max_daily_losses": int(os.environ.get("MAX_DAILY_LOSSES", 3)),
            "max_daily_loss_usd": float(os.environ.get("MAX_DAILY_LOSS_USD", 100)),
            "lot_size_forex": float(os.environ.get("LOT_SIZE_FOREX", 1.0)),
            "lot_size_gold": float(os.environ.get("LOT_SIZE_GOLD", 0.1)),
            "tp_pips_forex": int(os.environ.get("TP_PIPS_FOREX", 2)),
            "sl_pips_forex": int(os.environ.get("SL_PIPS_FOREX", 5)),
            "tp_pips_gold": int(os.environ.get("TP_PIPS_GOLD", 20)),
            "sl_pips_gold": int(os.environ.get("SL_PIPS_GOLD", 50)),
            "asia_start": int(os.environ.get("ASIA_START", 1)),
            "asia_end": int(os.environ.get("ASIA_END", 6)),
            "london_start": int(os.environ.get("LONDON_START", 8)),
            "london_end": int(os.environ.get("LONDON_END", 12)),
            "ny_start": int(os.environ.get("NY_START", 13)),
            "ny_end": int(os.environ.get("NY_END", 20)),
        },
    )

    # Create SymbolConfig rows for each symbol in SYMBOLS env var
    symbols_str = os.environ.get("SYMBOLS", "USDJPYm,EURUSDm")
    for symbol in symbols_str.split(","):
        symbol = symbol.strip()
        if symbol:
            SymbolConfig.objects.get_or_create(symbol=symbol)


def reverse_seed(apps, schema_editor):
    # No-op: don't delete config on reverse
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("trading", "0002_add_trading_config_symbol_config"),
    ]

    operations = [
        migrations.RunPython(seed_config, reverse_seed),
    ]
