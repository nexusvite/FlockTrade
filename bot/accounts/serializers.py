"""
accounts/serializers.py

DRF serializers for authentication, user profile management,
and audit log read access.
"""

import logging

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import AuditLog, UserProfile, UserRole

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth serializers
# ---------------------------------------------------------------------------


class LoginSerializer(serializers.Serializer):
    """Validates credentials and returns the Django User on success."""

    username = serializers.CharField(
        max_length=150,
        trim_whitespace=True,
    )
    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    def validate(self, attrs: dict) -> dict:
        username = attrs.get("username")
        password = attrs.get("password")

        if not username or not password:
            raise serializers.ValidationError(
                "Both username and password are required.",
                code="missing_credentials",
            )

        user = authenticate(
            request=self.context.get("request"),
            username=username,
            password=password,
        )

        if user is None:
            raise serializers.ValidationError(
                "Invalid credentials. Please check your username and password.",
                code="invalid_credentials",
            )

        if not user.is_active:
            raise serializers.ValidationError(
                "This account has been deactivated.",
                code="account_disabled",
            )

        attrs["user"] = user
        return attrs


class RegisterSerializer(serializers.ModelSerializer):
    """
    Creates a new Django User with an associated UserProfile.

    Endpoint is restricted to admin users only at the view level;
    this serializer handles data validation and creation logic.
    """

    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        validators=[validate_password],
    )
    password_confirm = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )
    role = serializers.ChoiceField(
        choices=UserRole.choices,
        default=UserRole.VIEWER,
        required=False,
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "password",
            "password_confirm",
            "first_name",
            "last_name",
            "role",
        ]
        extra_kwargs = {
            "email": {"required": True},
            "first_name": {"required": False},
            "last_name": {"required": False},
        }

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "A user with this email address already exists."
            )
        return value

    def validate_username(self, value: str) -> str:
        value = value.strip()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError(
                "This username is already taken."
            )
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        return attrs

    def create(self, validated_data: dict) -> User:
        role = validated_data.pop("role", "viewer")
        password = validated_data.pop("password")

        user = User.objects.create_user(
            password=password,
            **validated_data,
        )

        UserProfile.objects.create(user=user, role=role)
        logger.info("New user registered: %s (role=%s)", user.username, role)
        return user


# ---------------------------------------------------------------------------
# Profile serializers
# ---------------------------------------------------------------------------


class UserProfileSerializer(serializers.ModelSerializer):
    """Read/write serializer for UserProfile with nested User fields."""

    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    is_staff = serializers.BooleanField(source="user.is_staff", read_only=True)
    date_joined = serializers.DateTimeField(source="user.date_joined", read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = UserProfile
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "date_joined",
            "role",
            "role_display",
            "telegram_chat_id",
            "notification_enabled",
            "two_factor_enabled",
            "last_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "role",           # role changes must go through a dedicated admin endpoint
            "last_active",
            "created_at",
            "updated_at",
        ]

    def validate_telegram_chat_id(self, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if value and not value.lstrip("-").isdigit():
                raise serializers.ValidationError(
                    "Telegram chat ID must be a numeric value."
                )
        return value or None


class MeSerializer(serializers.ModelSerializer):
    """
    Compact current-user serializer returned by GET /api/auth/me/.
    Embeds profile data directly to avoid a second round-trip.
    """

    profile = UserProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "date_joined",
            "last_login",
            "profile",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Password management
# ---------------------------------------------------------------------------


class ChangePasswordSerializer(serializers.Serializer):
    """
    Validates the current password before accepting a new one.
    Enforces Django's AUTH_PASSWORD_VALIDATORS rules on new_password.
    """

    old_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )
    new_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        validators=[validate_password],
    )
    new_password_confirm = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    def validate_old_password(self, value: str) -> str:
        user: User = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError(
                "Your current password is incorrect.",
                code="wrong_password",
            )
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "New passwords do not match."}
            )
        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "New password must differ from the current one."}
            )
        return attrs

    def save(self, **kwargs) -> User:
        user: User = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        logger.info("Password changed for user: %s", user.username)
        return user


# ---------------------------------------------------------------------------
# Token response helper
# ---------------------------------------------------------------------------


class TokenPairSerializer(serializers.Serializer):
    """Serializer for the JWT token pair response body."""

    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    user = MeSerializer(read_only=True)

    @staticmethod
    def get_tokens_for_user(user: User) -> dict:
        refresh = RefreshToken.for_user(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class AuditLogSerializer(serializers.ModelSerializer):
    """Read-only serializer for audit log entries (admin/staff access)."""

    username = serializers.SerializerMethodField()
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "username",
            "action",
            "action_display",
            "ip_address",
            "user_agent",
            "details",
            "timestamp",
        ]
        read_only_fields = fields

    def get_username(self, obj: AuditLog) -> str | None:
        return obj.user.username if obj.user else None
