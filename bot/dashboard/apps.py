"""
dashboard/apps.py

AppConfig for the dashboard app.

The ``ready()`` hook connects the ``post_save`` signal receivers defined in
``dashboard/signals.py`` to the ``trading.Trade`` and ``ai.AIDecision``
models.  This is the canonical Django pattern for wiring signals: import
receiver functions (not modules) inside ``ready()`` so they are registered
exactly once per worker process, even when Django's auto-reloader restarts.

The ``bot_status_changed`` custom signal uses the ``@receiver`` decorator
directly in signals.py, so no explicit ``connect()`` call is needed here.
"""

from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"
    verbose_name = "Dashboard"

    def ready(self) -> None:
        """
        Wire up post_save signal receivers for Trade and AIDecision models.

        Models are imported inside ``ready()`` to avoid the "Apps aren't
        loaded yet" error that occurs when models are imported at module
        level in an AppConfig subclass.
        """
        from dashboard.signals import on_ai_decision, on_trade_closed, on_trade_created

        # ---------------------------------------------------------------------------
        # trading.Trade → post_save
        # ---------------------------------------------------------------------------
        try:
            from django.apps import apps

            Trade = apps.get_model("trading", "Trade")  # noqa: N806

            from django.db.models.signals import post_save

            # on_trade_created: fires only when created=True (new trade opened)
            post_save.connect(
                on_trade_created,
                sender=Trade,
                dispatch_uid="dashboard.on_trade_created",
            )

            # on_trade_closed: fires on UPDATE when exit_price is populated
            post_save.connect(
                on_trade_closed,
                sender=Trade,
                dispatch_uid="dashboard.on_trade_closed",
            )

            logger.debug("dashboard: connected trade signals to trading.Trade")
        except LookupError:
            # trading app / Trade model not yet registered — signals will not
            # fire.  This is expected during initial migrations.
            logger.debug(
                "dashboard: trading.Trade not found — trade signals not connected. "
                "This is normal before migrations are run."
            )

        # ---------------------------------------------------------------------------
        # ai.AIDecision → post_save
        # ---------------------------------------------------------------------------
        try:
            from django.apps import apps

            AIDecision = apps.get_model("ai", "AIDecision")  # noqa: N806

            from django.db.models.signals import post_save

            post_save.connect(
                on_ai_decision,
                sender=AIDecision,
                dispatch_uid="dashboard.on_ai_decision",
            )

            logger.debug("dashboard: connected ai_decision signal to ai.AIDecision")
        except LookupError:
            logger.debug(
                "dashboard: ai.AIDecision not found — ai decision signal not connected. "
                "This is normal before migrations are run."
            )
