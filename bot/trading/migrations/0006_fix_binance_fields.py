"""
Safe migration that ensures all Binance fields exist.
Uses RunSQL with IF NOT EXISTS to handle partial previous migrations.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("trading", "0005_binance_account_type"),
    ]

    operations = [
        # Ensure account_type exists on trades
        migrations.RunSQL(
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS account_type VARCHAR(4) DEFAULT 'DEMO';",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS binance_order_id VARCHAR(50) DEFAULT '';",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Ensure account_type exists on bot_status
        migrations.RunSQL(
            "ALTER TABLE bot_status ADD COLUMN IF NOT EXISTS account_type VARCHAR(4) DEFAULT 'DEMO';",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Rename connected_to_mt5 if it still exists
        migrations.RunSQL(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='bot_status' AND column_name='connected_to_mt5') THEN
                    ALTER TABLE bot_status RENAME COLUMN connected_to_mt5 TO connected_to_exchange;
                END IF;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Ensure connected_to_exchange exists (in case neither name existed)
        migrations.RunSQL(
            "ALTER TABLE bot_status ADD COLUMN IF NOT EXISTS connected_to_exchange BOOLEAN DEFAULT FALSE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Ensure account_type exists on daily_stats
        migrations.RunSQL(
            "ALTER TABLE daily_stats ADD COLUMN IF NOT EXISTS account_type VARCHAR(4) DEFAULT 'DEMO';",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Add unique constraint on bot_status.account_type if not exists
        migrations.RunSQL(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bot_status_account_type_uniq') THEN
                    -- First ensure no duplicate account_types
                    DELETE FROM bot_status WHERE id NOT IN (
                        SELECT MIN(id) FROM bot_status GROUP BY account_type
                    );
                    ALTER TABLE bot_status ADD CONSTRAINT bot_status_account_type_uniq UNIQUE (account_type);
                END IF;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Create indexes if not exist
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS trades_account_type_idx ON trades (account_type);",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS bot_status_account_type_idx ON bot_status (account_type);",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS daily_stats_account_type_idx ON daily_stats (account_type);",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
