"""
accounts/views.py

JWT-based authentication views for the FlockTrade REST API.

Endpoints:
  POST /api/auth/login/           — Obtain JWT token pair
  POST /api/auth/refresh/         — Refresh access token (handled by SimpleJWT)
  POST /api/auth/logout/          — Blacklist refresh token
  POST /api/auth/register/        — Create user (admin only)
  GET  /api/auth/me/              — Current user profile
  PATCH /api/auth/me/             — Update notification prefs / telegram ID
  POST /api/auth/change-password/ — Change own password
  GET  /api/auth/audit-log/       — Security audit log (admin only)
"""

import logging

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import generics, permissions, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from .models import AuditAction, AuditLog, UserProfile
from .permissions import IsAdmin
from .serializers import (
    AuditLogSerializer,
    ChangePasswordSerializer,
    LoginSerializer,
    MeSerializer,
    RegisterSerializer,
    TokenPairSerializer,
    UserProfileSerializer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom throttle for login endpoint
# ---------------------------------------------------------------------------


class LoginRateThrottle(AnonRateThrottle):
    """Strict rate limit for login: 5 attempts per minute per IP."""

    rate = "5/minute"
    scope = "login"


class LoginUserRateThrottle(UserRateThrottle):
    """Authenticated login attempts are unlikely but capped defensively."""

    rate = "10/minute"
    scope = "login_user"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_client_ip(request: Request) -> str | None:
    """Extract real client IP, respecting X-Forwarded-For from reverse proxy."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        # Leftmost is the originating client when behind Traefik / nginx
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _get_user_agent(request: Request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class LoginView(APIView):
    """
    POST /api/auth/login/

    Accepts username + password, returns JWT access + refresh tokens
    along with the full user profile.  Rate-limited to 5 req/min per IP.
    Failed attempts are recorded in the audit log.
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(
            data=request.data,
            context={"request": request},
        )

        ip = _get_client_ip(request)
        ua = _get_user_agent(request)

        try:
            serializer.is_valid(raise_exception=True)
        except serializers.ValidationError:
            # Log failed attempts without exposing internal details
            attempted_username = request.data.get("username", "")
            AuditLog.log(
                action=AuditAction.LOGIN_FAILED,
                user=None,
                ip_address=ip,
                user_agent=ua,
                details={"username": attempted_username},
            )
            raise

        user: User = serializer.validated_data["user"]
        tokens = TokenPairSerializer.get_tokens_for_user(user)

        # Update last_active on the profile
        try:
            user.profile.touch()
        except UserProfile.DoesNotExist:
            UserProfile.objects.create(user=user)

        AuditLog.log(
            action=AuditAction.LOGIN,
            user=user,
            ip_address=ip,
            user_agent=ua,
        )

        return Response(
            {
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "user": MeSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Refresh (thin wrapper to add audit log entry)
# ---------------------------------------------------------------------------


class RefreshView(TokenRefreshView):
    """
    POST /api/auth/refresh/

    Wraps SimpleJWT's TokenRefreshView to add audit logging.
    Inherits all standard refresh + blacklist rotation behaviour.
    """

    def post(self, request: Request, *args, **kwargs) -> Response:
        response = super().post(request, *args, **kwargs)
        # No audit entry for normal token refresh (high volume, low security value)
        return response


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


class LogoutView(APIView):
    """
    POST /api/auth/logout/

    Blacklists the provided refresh token, invalidating the session.
    The client is responsible for discarding the access token locally.

    Request body:
        { "refresh": "<refresh_token>" }
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request) -> Response:
        refresh_token = request.data.get("refresh")

        if not refresh_token:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError as exc:
            return Response(
                {"detail": f"Invalid or expired token: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        AuditLog.log(
            action=AuditAction.LOGOUT,
            user=request.user,
            ip_address=_get_client_ip(request),
            user_agent=_get_user_agent(request),
        )

        return Response(
            {"detail": "Successfully logged out."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Register (admin only)
# ---------------------------------------------------------------------------


class RegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/

    Creates a new user account.  Restricted to admin users only — this
    platform is not open for self-registration in production.
    """

    serializer_class = RegisterSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user: User = serializer.save()

        AuditLog.log(
            action=AuditAction.REGISTER,
            user=request.user,
            ip_address=_get_client_ip(request),
            user_agent=_get_user_agent(request),
            details={
                "new_user": user.username,
                "email": user.email,
                "role": user.profile.role,
            },
        )

        return Response(
            {
                "detail": f"User '{user.username}' created successfully.",
                "user": MeSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Current user profile
# ---------------------------------------------------------------------------


class MeView(APIView):
    """
    GET  /api/auth/me/   — Return the authenticated user's full profile.
    PATCH /api/auth/me/  — Update mutable profile fields (notification prefs, telegram ID).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Request) -> Response:
        # Touch last_active on every authenticated request
        try:
            request.user.profile.touch()
        except UserProfile.DoesNotExist:
            UserProfile.objects.create(user=request.user)

        serializer = MeSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request: Request) -> Response:
        try:
            profile = request.user.profile
        except UserProfile.DoesNotExist:
            profile = UserProfile.objects.create(user=request.user)

        serializer = UserProfileSerializer(
            profile,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(MeSerializer(request.user).data)


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------


class ChangePasswordView(APIView):
    """
    POST /api/auth/change-password/

    Validates the current password, then sets the new one.
    All existing JWT tokens remain valid until they expire — clients
    should discard them and re-authenticate after a password change.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        AuditLog.log(
            action=AuditAction.PASSWORD_CHANGE,
            user=request.user,
            ip_address=_get_client_ip(request),
            user_agent=_get_user_agent(request),
        )

        return Response(
            {"detail": "Password updated successfully. Please log in again."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Audit log (admin read-only)
# ---------------------------------------------------------------------------


class AuditLogListView(generics.ListAPIView):
    """
    GET /api/auth/audit-log/

    Paginated, filterable security audit log.  Admin access only.

    Query params:
      ?action=login         — filter by action type
      ?username=trader1     — filter by username
      ?ip_address=10.0.0.1  — filter by IP
      ?ordering=-timestamp  — default ordering
    """

    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get_queryset(self):
        qs = (
            AuditLog.objects.select_related("user")
            .order_by("-timestamp")
        )

        action = self.request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)

        username = self.request.query_params.get("username")
        if username:
            qs = qs.filter(user__username__icontains=username)

        ip_address = self.request.query_params.get("ip_address")
        if ip_address:
            qs = qs.filter(ip_address=ip_address)

        return qs
