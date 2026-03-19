"""Update TradingConfig mt5_host from env var if still using old default."""

import os
from django.db import migrations


def update_mt5_host(apps, schema_editor):
    TradingConfig = apps.get_model("trading", "TradingConfig")
    env_host = os.environ.get("MT5_HOST", "")
    if not env_host:
        return

    TradingConfig.objects.filter(pk=1, mt5_host="mt5-trading").update(
        mt5_host=env_host,
        mt5_port=int(os.environ.get("MT5_PORT", 8001)),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("trading", "0003_seed_config_from_env"),
    ]

    operations = [
        migrations.RunPython(update_mt5_host, migrations.RunPython.noop),
    ]
