"""Ensure Binance schema fields exist (idempotent)."""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Add missing columns for Binance migration (safe to run multiple times)"

    def handle(self, *args, **options):
        with connection.cursor() as c:
            sqls = [
                "ALTER TABLE trades ADD COLUMN IF NOT EXISTS account_type VARCHAR(4) DEFAULT 'DEMO'",
                "ALTER TABLE trades ADD COLUMN IF NOT EXISTS binance_order_id VARCHAR(50) DEFAULT ''",
                "CREATE INDEX IF NOT EXISTS trades_account_type_idx ON trades (account_type)",
                "ALTER TABLE bot_status ADD COLUMN IF NOT EXISTS account_type VARCHAR(4) DEFAULT 'DEMO'",
                "ALTER TABLE bot_status ADD COLUMN IF NOT EXISTS connected_to_exchange BOOLEAN DEFAULT FALSE",
                "CREATE INDEX IF NOT EXISTS bot_status_account_type_idx ON bot_status (account_type)",
                "ALTER TABLE daily_stats ADD COLUMN IF NOT EXISTS account_type VARCHAR(4) DEFAULT 'DEMO'",
                "CREATE INDEX IF NOT EXISTS daily_stats_account_type_idx ON daily_stats (account_type)",
            ]
            for sql in sqls:
                try:
                    c.execute(sql)
                    self.stdout.write(f"  OK: {sql[:60]}...")
                except Exception as e:
                    self.stdout.write(f"  SKIP: {e}")

            # Drop old connected_to_mt5 column if it exists
            try:
                c.execute("""
                    DO $$ BEGIN
                        IF EXISTS (SELECT 1 FROM information_schema.columns
                                   WHERE table_name='bot_status' AND column_name='connected_to_mt5') THEN
                            ALTER TABLE bot_status DROP COLUMN connected_to_mt5;
                        END IF;
                    END $$;
                """)
                self.stdout.write("  OK: dropped connected_to_mt5 if existed")
            except Exception as e:
                self.stdout.write(f"  SKIP: {e}")

            # Add unique constraint on account_type
            try:
                c.execute("""
                    DO $$ BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                                       WHERE conname = 'bot_status_account_type_uniq') THEN
                            DELETE FROM bot_status WHERE id NOT IN (
                                SELECT MIN(id) FROM bot_status GROUP BY account_type
                            );
                            ALTER TABLE bot_status ADD CONSTRAINT bot_status_account_type_uniq
                                UNIQUE (account_type);
                        END IF;
                    END $$;
                """)
                self.stdout.write("  OK: unique constraint on account_type")
            except Exception as e:
                self.stdout.write(f"  SKIP: {e}")

        self.stdout.write(self.style.SUCCESS("Schema fix complete."))
