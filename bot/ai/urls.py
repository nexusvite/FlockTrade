"""
URL configuration for the AI app.

Mounted at /api/ai/ in flocktrade/urls.py:
    path("api/ai/", include("ai.urls"))

Available endpoints:
    GET  /api/ai/decisions/          Paginated list of AI decisions
    GET  /api/ai/decisions/<uuid>/   Single decision detail with full context
    GET  /api/ai/costs/              Cost breakdown by model and day
"""
from django.urls import path

from .views import AIDecisionDetailView, AIDecisionListView, AICostView

app_name = "ai"

urlpatterns = [
    # AI decision log
    path(
        "decisions/",
        AIDecisionListView.as_view(),
        name="decision-list",
    ),
    path(
        "decisions/<uuid:pk>/",
        AIDecisionDetailView.as_view(),
        name="decision-detail",
    ),
    # Cost dashboard data
    path(
        "costs/",
        AICostView.as_view(),
        name="cost-breakdown",
    ),
]
