"""
Add Binance support: account_type fields, rename connected_to_mt5,
add account_type to DailyStats, add binance_order_id to Trade.
"""
from django.db import migrations, models


def migrate_botstatus_data(apps, schema_editor):
    """Set account_type='DEMO' on existing BotStatus rows."""
    BotStatus = apps.get_model("trading", "BotStatus")
    BotStatus.objects.filter(account_type="").update(account_type="DEMO")


def migrate_trade_data(apps, schema_editor):
    """Set account_type='DEMO' on existing Trade rows."""
    Trade = apps.get_model("trading", "Trade")
    Trade.objects.filter(account_type="").update(account_type="DEMO")


def convert_daily_stats_pk(apps, schema_editor):
    """Convert DailyStats from date-PK to auto-PK using raw SQL."""
    db = schema_editor.connection
    if db.vendor == "postgresql":
        # Add id column, make it the new PK
        schema_editor.execute(
            "ALTER TABLE daily_stats ADD COLUMN id SERIAL;"
        )
        schema_editor.execute(
            "ALTER TABLE daily_stats DROP CONSTRAINT IF EXISTS daily_stats_pkey;"
        )
        schema_editor.execute(
            "ALTER TABLE daily_stats ADD PRIMARY KEY (id);"
        )
        # Add account_type column
        schema_editor.execute(
            "ALTER TABLE daily_stats ADD COLUMN account_type VARCHAR(4) NOT NULL DEFAULT 'DEMO';"
        )
        # Add unique constraint and indexes
        schema_editor.execute(
            "ALTER TABLE daily_stats ADD CONSTRAINT daily_stats_date_account_uniq UNIQUE (date, account_type);"
        )
        schema_editor.execute(
            "CREATE INDEX IF NOT EXISTS daily_stats_account_type_idx ON daily_stats (account_type);"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("trading", "0004_update_mt5_host_from_env"),
    ]

    operations = [
        # --- Trade model ---
        migrations.AddField(
            model_name="trade",
            name="account_type",
            field=models.CharField(
                choices=[("DEMO", "Demo"), ("REAL", "Real")],
                db_index=True,
                default="DEMO",
                max_length=4,
            ),
        ),
        migrations.AddField(
            model_name="trade",
            name="binance_order_id",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.RunPython(migrate_trade_data, migrations.RunPython.noop),

        # --- BotStatus model ---
        migrations.AddField(
            model_name="botstatus",
            name="account_type",
            field=models.CharField(
                choices=[("DEMO", "Demo"), ("REAL", "Real")],
                db_index=True,
                default="DEMO",
                max_length=4,
            ),
        ),
        migrations.RenameField(
            model_name="botstatus",
            old_name="connected_to_mt5",
            new_name="connected_to_exchange",
        ),
        migrations.RunPython(migrate_botstatus_data, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="botstatus",
            name="account_type",
            field=models.CharField(
                choices=[("DEMO", "Demo"), ("REAL", "Real")],
                db_index=True,
                default="DEMO",
                max_length=4,
                unique=True,
            ),
        ),

        # --- DailyStats model ---
        migrations.RunPython(convert_daily_stats_pk, migrations.RunPython.noop),
    ]
