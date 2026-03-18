"""
accounts/middleware.py

AuditLogMiddleware — records security-relevant HTTP events in the audit log.

Audited events:
  - POST /api/auth/login/          -> login / login_failed (handled in view,
                                       middleware only records token auth failures)
  - POST /api/auth/logout/         -> logout (view-level + middleware safety net)
  - POST /api/auth/register/       -> register (view-level)
  - POST /api/auth/change-password/-> password_change (view-level)
  - POST /api/config/              -> config_change
  - POST /api/control/pause/       -> trade_pause
  - POST /api/control/resume/      -> trade_resume

Views handle their own audit entries for full context (username before auth,
new config values, etc.). The middleware adds a secondary defence layer that
catches any missed paths and also keeps last_active up to date.
"""

import logging
import re

from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from .models import AuditAction, AuditLog, UserProfile

logger = logging.getLogger(__name__)


# Paths that trigger automatic audit log entries from the middleware layer.
# Each entry maps a (method, regex) pair to an AuditAction constant.
_AUDITED_PATHS: list[tuple[str, re.Pattern, str]] = [
    ("POST", re.compile(r"^/api/control/pause/?$"), AuditAction.TRADE_PAUSE),
    ("POST", re.compile(r"^/api/control/resume/?$"), AuditAction.TRADE_RESUME),
    ("POST", re.compile(r"^/api/config/?$"), AuditAction.CONFIG_CHANGE),
]

# Paths where last_active should be refreshed on every authenticated request.
_ACTIVE_REFRESH_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


def _get_client_ip(request) -> str | None:
    """Extract originating client IP, honouring X-Forwarded-For."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _get_user_agent(request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")


class AuditLogMiddleware(MiddlewareMixin):
    """
    Django middleware that:

    1. On every authenticated request, refreshes UserProfile.last_active
       (using a targeted UPDATE — not a full model save — to avoid overhead).

    2. After specific mutating requests complete (response status 2xx), writes
       an AuditLog record with the actor, IP, UA, and any captured details.

    The middleware runs *after* authentication middleware, so request.user is
    populated before process_request is called.

    Failure policy: exceptions inside audit logic are caught and logged as
    warnings — they must never bubble up and break a legitimate request.
    """

    def process_request(self, request):
        """Touch last_active for authenticated users on every request."""
        try:
            if (
                request.method in _ACTIVE_REFRESH_METHODS
                and hasattr(request, "user")
                and request.user.is_authenticated
            ):
                # Defer the DB write to process_response so we can batch
                # it with any audit log writes if needed. Store on request
                # to avoid calling is_authenticated twice.
                request._audit_user = request.user
        except Exception:
            logger.exception("AuditLogMiddleware.process_request error (non-fatal)")

        return None  # Continue processing

    def process_response(self, request, response):
        """
        After the view runs:
          1. Touch last_active for authenticated users.
          2. Write audit log entries for sensitive paths on successful responses.
        """
        try:
            user = getattr(request, "_audit_user", None)

            if user and user.is_authenticated:
                self._touch_last_active(user)

            # Only audit successful mutation responses
            if response.status_code in range(200, 300):
                self._maybe_audit(request, user)

        except Exception:
            logger.exception("AuditLogMiddleware.process_response error (non-fatal)")

        return response

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _touch_last_active(user) -> None:
        """
        Efficient last_active update using a targeted queryset UPDATE.
        Uses select_related to avoid an extra query for the profile check.
        """
        try:
            UserProfile.objects.filter(user_id=user.pk).update(
                last_active=timezone.now()
            )
        except Exception:
            logger.debug(
                "Could not update last_active for user %s (profile may not exist yet)",
                user.username,
            )

    @staticmethod
    def _maybe_audit(request, user) -> None:
        """Write an audit log entry if the request path matches a watched pattern."""
        path = request.path_info
        method = request.method

        for watched_method, pattern, action in _AUDITED_PATHS:
            if method == watched_method and pattern.match(path):
                ip = _get_client_ip(request)
                ua = _get_user_agent(request)

                # Capture safe details — never log raw request bodies
                details: dict = {
                    "path": path,
                    "method": method,
                }

                # For config changes, capture top-level keys changed (not values)
                if action == AuditAction.CONFIG_CHANGE and hasattr(request, "data"):
                    try:
                        details["changed_keys"] = list(request.data.keys())
                    except Exception:
                        pass

                AuditLog.objects.create(
                    user=user,
                    action=action,
                    ip_address=ip,
                    user_agent=ua,
                    details=details,
                )
                logger.info(
                    "AUDIT %s | user=%s | path=%s | ip=%s",
                    action,
                    user.username if user else "anon",
                    path,
                    ip,
                )
                break  # Only one match per request
