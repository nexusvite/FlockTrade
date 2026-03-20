"""Replace forex symbols with crypto symbols in the database."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Replace old forex SymbolConfig entries with crypto pairs"

    def handle(self, *args, **options):
        from trading.models import SymbolConfig

        # Delete old forex symbols
        deleted, _ = SymbolConfig.objects.filter(symbol__endswith="m").delete()
        deleted2, _ = SymbolConfig.objects.filter(symbol__contains="GBP").delete()
        self.stdout.write(f"Deleted {deleted + deleted2} old forex symbols")

        # Upsert crypto symbols via Django ORM
        crypto_symbols = [
            # (symbol, enabled, lot_size, tp_pips, sl_pips, max_spread_pips)
            ("BTCUSDT", True, 0.001, 200, 100, 50.0),
            ("ETHUSDT", True, 0.01, 200, 100, 20.0),
            ("XRPUSDT", True, 10.0, 50, 25, 0.5),
        ]
        for sym, enabled, lot, tp, sl, spread in crypto_symbols:
            obj, created = SymbolConfig.objects.update_or_create(
                symbol=sym,
                defaults={
                    "enabled": enabled,
                    "lot_size": lot,
                    "tp_pips": tp,
                    "sl_pips": sl,
                    "max_spread_pips": spread,
                },
            )
            status = "Created" if created else "Updated"
            self.stdout.write(f"  {status} {sym} (lot={lot}, tp={tp}, sl={sl})")

        self.stdout.write(self.style.SUCCESS("Crypto setup complete."))
