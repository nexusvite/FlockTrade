"""
Add Binance support: account_type fields, rename connected_to_mt5,
convert DailyStats to per-account, add binance_order_id to Trade.
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


def recreate_daily_stats(apps, schema_editor):
    """
    Migrate DailyStats from date-PK to auto-PK with account_type.

    Since we're changing the primary key, we use raw SQL to:
    1. Create the new table
    2. Copy existing data with account_type='DEMO'
    3. Drop old table
    4. Rename new table
    """
    db = schema_editor.connection
    # Only run raw SQL for PostgreSQL; skip for SQLite test databases
    if db.vendor == "postgresql":
        schema_editor.execute("""
            CREATE TABLE daily_stats_new (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                account_type VARCHAR(4) NOT NULL DEFAULT 'DEMO',
                trades INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                scratches INTEGER NOT NULL DEFAULT 0,
                pnl NUMERIC(10,2) NOT NULL DEFAULT 0,
                ai_cost NUMERIC(10,4) NOT NULL DEFAULT 0,
                best_trade NUMERIC(10,2) NULL,
                worst_trade NUMERIC(10,2) NULL,
                UNIQUE (date, account_type)
            );
        """)
        schema_editor.execute("""
            INSERT INTO daily_stats_new (date, account_type, trades, wins, losses, scratches, pnl, ai_cost, best_trade, worst_trade)
            SELECT date, 'DEMO', trades, wins, losses, scratches, pnl, ai_cost, best_trade, worst_trade
            FROM daily_stats;
        """)
        schema_editor.execute("DROP TABLE daily_stats;")
        schema_editor.execute("ALTER TABLE daily_stats_new RENAME TO daily_stats;")
        schema_editor.execute("CREATE INDEX daily_stats_date_idx ON daily_stats (date);")
        schema_editor.execute("CREATE INDEX daily_stats_account_type_idx ON daily_stats (account_type);")
        schema_editor.execute("CREATE INDEX daily_stats_date_account_idx ON daily_stats (date, account_type);")
    else:
        # SQLite fallback for testing
        schema_editor.execute("""
            CREATE TABLE daily_stats_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                account_type VARCHAR(4) NOT NULL DEFAULT 'DEMO',
                trades INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                scratches INTEGER NOT NULL DEFAULT 0,
                pnl DECIMAL(10,2) NOT NULL DEFAULT 0,
                ai_cost DECIMAL(10,4) NOT NULL DEFAULT 0,
                best_trade DECIMAL(10,2) NULL,
                worst_trade DECIMAL(10,2) NULL,
                UNIQUE (date, account_type)
            );
        """)
        schema_editor.execute("""
            INSERT INTO daily_stats_new (date, account_type, trades, wins, losses, scratches, pnl, ai_cost, best_trade, worst_trade)
            SELECT date, 'DEMO', trades, wins, losses, scratches, pnl, ai_cost, best_trade, worst_trade
            FROM daily_stats;
        """)
        schema_editor.execute("DROP TABLE daily_stats;")
        schema_editor.execute("ALTER TABLE daily_stats_new RENAME TO daily_stats;")


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
        # Add account_type field (not unique yet)
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
        # Rename connected_to_mt5 -> connected_to_exchange
        migrations.RenameField(
            model_name="botstatus",
            old_name="connected_to_mt5",
            new_name="connected_to_exchange",
        ),
        # Migrate existing data
        migrations.RunPython(migrate_botstatus_data, migrations.RunPython.noop),
        # Now make account_type unique
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
        # Recreate the table with new PK structure using raw SQL
        migrations.RunPython(recreate_daily_stats, migrations.RunPython.noop),
    ]
