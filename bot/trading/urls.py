"""
URL patterns for the Trading app.

Mounted at /api/ in flocktrade/urls.py.

All endpoints require JWT authentication. Role requirements per view:
    Viewer / Trader / Admin: GET endpoints
    Trader / Admin:          POST /control/
    Admin only:              PATCH /config/
"""
from django.urls import path

from trading.views import (
    BotControlView,
    BotStatusView,
    ConfigView,
    DailyStatsListView,
    PerformanceView,
    SRLevelListView,
    TradeDetailView,
    TradeListView,
)

app_name = "trading"

urlpatterns = [
    # --- Trade history ---
    # GET  /api/trades/       — Paginated list with filters
    path("trades/", TradeListView.as_view(), name="trade-list"),
    # GET  /api/trades/{pk}/  — Full detail with AI reasoning
    path("trades/<uuid:pk>/", TradeDetailView.as_view(), name="trade-detail"),

    # --- Support/Resistance levels ---
    # GET  /api/levels/       — Current S/R map (filterable by symbol, strength)
    path("levels/", SRLevelListView.as_view(), name="sr-level-list"),

    # --- Performance analytics ---
    # GET  /api/performance/  — Win rate, P&L, per-symbol breakdown
    #                           ?period=today|7d|30d|all  &symbol=USDJPYm
    path("performance/", PerformanceView.as_view(), name="performance"),

    # --- Daily stats ---
    # GET  /api/daily-stats/  — Day-by-day performance table
    #                           ?days=30
    path("daily-stats/", DailyStatsListView.as_view(), name="daily-stats"),

    # --- Bot status ---
    # GET  /api/status/       — Current bot state, MT5 connectivity, balances
    path("status/", BotStatusView.as_view(), name="bot-status"),

    # --- Bot control ---
    # POST /api/control/      — { "action": "pause"|"resume"|"stop"|"start" }
    #                           Requires Trader or Admin role
    path("control/", BotControlView.as_view(), name="bot-control"),

    # --- Configuration ---
    # GET  /api/config/       — Current settings snapshot
    # PATCH /api/config/      — Update settings (Admin only)
    path("config/", ConfigView.as_view(), name="config"),
]
