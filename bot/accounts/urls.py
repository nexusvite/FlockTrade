"""
accounts/urls.py

URL patterns for the accounts (auth) app.

Mounted at /api/auth/ by the root flocktrade/urls.py:

  POST   /api/auth/login/            — Obtain JWT token pair
  POST   /api/auth/refresh/          — Rotate access token using refresh token
  POST   /api/auth/logout/           — Blacklist refresh token
  POST   /api/auth/register/         — Create new user (admin only)
  GET    /api/auth/me/               — Current user profile
  PATCH  /api/auth/me/               — Update profile (notifications, telegram ID)
  POST   /api/auth/change-password/  — Change own password
  GET    /api/auth/audit-log/        — Security audit trail (admin only)
"""

from django.urls import path

from .views import (
    AuditLogListView,
    ChangePasswordView,
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    RegisterView,
)

app_name = "accounts"

urlpatterns = [
    # Authentication
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", RefreshView.as_view(), name="token_refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),

    # User management (admin only for register)
    path("register/", RegisterView.as_view(), name="register"),

    # Current user
    path("me/", MeView.as_view(), name="me"),

    # Password management
    path("change-password/", ChangePasswordView.as_view(), name="change_password"),

    # Security audit log (admin only)
    path("audit-log/", AuditLogListView.as_view(), name="audit_log"),
]
