"""
accounts/permissions.py

Custom DRF permission classes for FlockTrade role-based access control.

Role hierarchy (highest to lowest):
    ADMIN  — full access: config, trades, users, audit log
    TRADER — read trades, P&L, AI logs; can pause/resume bot
    VIEWER — read-only dashboard access only

Permission classes compose naturally with DRF's permission system:

    permission_classes = [IsAuthenticated, IsAdmin]
    permission_classes = [IsAuthenticated, IsTrader]

Each class also accepts Django superusers (is_superuser=True) regardless
of the UserProfile.role value, so the initial Django admin account works
without needing a profile row.
"""

import logging

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from .models import UserProfile, UserRole

logger = logging.getLogger(__name__)


def _get_role(request: Request) -> str | None:
    """
    Safely return the UserProfile.role for an authenticated request user.

    Returns None if:
      - The user is anonymous
      - The user has no associated UserProfile (legacy / migration edge case)
    """
    if not request.user or not request.user.is_authenticated:
        return None
    try:
        return request.user.profile.role
    except UserProfile.DoesNotExist:
        logger.warning(
            "User %s has no UserProfile — denying role-based access.",
            request.user.username,
        )
        return None


class IsAdmin(BasePermission):
    """
    Allow access only to users with role == 'admin' or Django superusers.

    Use on endpoints that:
      - Register new users
      - Change bot configuration (pairs, models, risk params)
      - View the security audit log
      - Manage API keys for other users
    """

    message = "Access restricted to administrators."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        # Django superuser bypasses role check
        if request.user.is_superuser:
            return True

        return _get_role(request) == UserRole.ADMIN

    def has_object_permission(self, request: Request, view: APIView, obj) -> bool:
        return self.has_permission(request, view)


class IsTrader(BasePermission):
    """
    Allow access to users with role >= 'trader' (trader or admin).

    Use on endpoints that:
      - Return trade history and active positions
      - Show P&L and performance analytics
      - Provide AI decision logs
      - Allow pause/resume of trading bot
    """

    message = "Access restricted to traders and administrators."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        role = _get_role(request)
        return role in (UserRole.TRADER, UserRole.ADMIN)

    def has_object_permission(self, request: Request, view: APIView, obj) -> bool:
        return self.has_permission(request, view)


class IsViewer(BasePermission):
    """
    Allow access to any authenticated user (all roles can view the dashboard).

    All roles (admin, trader, viewer) pass this check, making it effectively
    equivalent to IsAuthenticated with role awareness.  Use this on endpoints
    where you want to be explicit about minimum access intent.
    """

    message = "You must be logged in to access this resource."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        # All valid roles pass — the check exists to reject users whose
        # profile is missing or whose role has been cleared.
        role = _get_role(request)
        return role in (UserRole.VIEWER, UserRole.TRADER, UserRole.ADMIN)

    def has_object_permission(self, request: Request, view: APIView, obj) -> bool:
        return self.has_permission(request, view)


class IsOwnerOrAdmin(BasePermission):
    """
    Object-level permission: allow access if the requesting user owns the
    object or is an administrator.

    The view must pass the object to check_object_permissions().
    The object must have either a `user` attribute or be a User instance.

    Usage:
        permission_classes = [IsAuthenticated, IsOwnerOrAdmin]
    """

    message = "You can only access your own resources."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request: Request, view: APIView, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        if _get_role(request) == UserRole.ADMIN:
            return True

        # Support objects that *are* a User, or objects with a .user FK
        from django.contrib.auth.models import User as DjangoUser
        if isinstance(obj, DjangoUser):
            return obj == request.user

        owner = getattr(obj, "user", None)
        return owner == request.user


class ReadOnly(BasePermission):
    """
    Allow GET, HEAD, OPTIONS; deny all mutating methods.

    Useful when combined with role permissions to give viewer-role users
    read access on endpoints that also allow traders/admins to write.

    Example:
        permission_classes = [IsAuthenticated, IsTrader | ReadOnly]
    """

    SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
    message = "This resource is read-only."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.method in self.SAFE_METHODS
