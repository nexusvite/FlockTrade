"""Increase lot_size decimal precision for crypto (e.g. 0.001 BTC)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("trading", "0005_binance_account_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="trade",
            name="lot_size",
            field=models.DecimalField(
                blank=True, decimal_places=6, max_digits=12, null=True,
            ),
        ),
        migrations.AlterField(
            model_name="symbolconfig",
            name="lot_size",
            field=models.DecimalField(
                blank=True, decimal_places=6, max_digits=12, null=True,
            ),
        ),
    ]
