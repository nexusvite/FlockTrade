"""Replace forex symbols with crypto symbols in the database."""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Replace old forex SymbolConfig entries with crypto pairs"

    def handle(self, *args, **options):
        with connection.cursor() as c:
            # Delete old forex symbols
            c.execute("DELETE FROM symbol_config WHERE symbol LIKE '%%USD%%m' OR symbol LIKE '%%GBP%%'")
            self.stdout.write("Deleted old forex symbols")

            # Update TradingConfig symbols
            c.execute(
                "UPDATE trading_config SET symbols = %s WHERE id = 1",
                ['BTCUSDT,ETHUSDT'],
            )
            self.stdout.write("Updated TradingConfig symbols")

            # Insert crypto symbols if not exist
            crypto_symbols = [
                ('BTCUSDT', 'CRYPTO', True, 0.001, 200, 100, 50.0),
                ('ETHUSDT', 'CRYPTO', True, 0.01, 200, 100, 20.0),
            ]
            for sym, typ, enabled, lot, tp, sl, spread in crypto_symbols:
                c.execute(
                    """INSERT INTO symbol_config (symbol, instrument_type, enabled, lot_size, tp_pips, sl_pips, max_spread_pips)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (symbol) DO UPDATE SET
                           instrument_type = EXCLUDED.instrument_type,
                           enabled = EXCLUDED.enabled""",
                    [sym, typ, enabled, lot, tp, sl, spread],
                )
                self.stdout.write(f"  Added/updated {sym}")

        self.stdout.write(self.style.SUCCESS("Crypto setup complete."))
