"""
accounts/models.py

User profile, API key management, and audit logging for FlockTrade.
Extends Django's built-in User model with role-based access control.
"""

import hashlib
import logging
import uuid

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


class UserRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    TRADER = "trader", "Trader"
    VIEWER = "viewer", "Viewer"


class APIKeyPermission(models.TextChoices):
    READ = "read", "Read"
    WRITE = "write", "Write"
    ADMIN = "admin", "Admin"


class UserProfile(models.Model):
    """
    Extended profile for Django's built-in User model.

    Stores role-based access control, Telegram notification preferences,
    2FA status, and last activity tracking. Every Django User created via
    the accounts system will have exactly one UserProfile.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_comment="UUID primary key for UserProfile",
    )
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        db_index=True,
    )
    role = models.CharField(
        max_length=10,
        choices=UserRole.choices,
        default=UserRole.VIEWER,
        db_index=True,
        db_comment="Role determines dashboard access level",
    )
    telegram_chat_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Telegram chat ID for trade notifications",
    )
    notification_enabled = models.BooleanField(
        default=True,
        help_text="Enable/disable all platform notifications",
    )
    two_factor_enabled = models.BooleanField(
        default=False,
        help_text="TOTP-based 2FA status (managed via django-allauth)",
    )
    last_active = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Timestamp of last authenticated request",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_profiles"
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
        indexes = [
            models.Index(fields=["role"], name="idx_userprofile_role"),
            models.Index(fields=["last_active"], name="idx_userprofile_last_active"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} ({self.get_role_display()})"

    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    def is_trader(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.TRADER)

    def is_viewer(self) -> bool:
        """All roles can at minimum view the dashboard."""
        return True

    def touch(self) -> None:
        """Update last_active timestamp without triggering full model save."""
        UserProfile.objects.filter(pk=self.pk).update(last_active=timezone.now())
        self.last_active = timezone.now()


class APIKey(models.Model):
    """
    Hashed API key for programmatic/service-to-service access.

    The raw key is shown to the user only once at creation time.
    Only the SHA-256 hash is persisted. Keys can have scoped
    permissions (read/write/admin) and optional expiration.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="api_keys",
        db_index=True,
    )
    key_hash = models.CharField(
        max_length=64,
        unique=True,
        help_text="SHA-256 hex digest of the raw API key",
        db_comment="SHA-256 hash — never store the raw key",
    )
    name = models.CharField(
        max_length=100,
        help_text="Human-readable label for this key (e.g. 'CI pipeline')",
    )
    permissions = models.CharField(
        max_length=10,
        choices=APIKeyPermission.choices,
        default=APIKeyPermission.READ,
        db_index=True,
    )
    last_used = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Timestamp of last successful authenticated request",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Optional expiry; null means no expiration",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "api_keys"
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_active"], name="idx_apikey_user_active"),
            models.Index(fields=["expires_at"], name="idx_apikey_expires"),
        ]

    def __str__(self) -> str:
        status = "active" if self.is_active else "revoked"
        return f"{self.name} ({self.user.username}) [{status}]"

    @property
    def is_expired(self) -> bool:
        """True if an expiry is set and has passed."""
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """Key is usable only when active and not expired."""
        return self.is_active and not self.is_expired

    @staticmethod
    def hash_key(raw_key: str) -> str:
        """Return SHA-256 hex digest of a raw API key string."""
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @classmethod
    def get_by_raw_key(cls, raw_key: str) -> "APIKey | None":
        """Look up an APIKey by its raw (unhashed) value."""
        key_hash = cls.hash_key(raw_key)
        try:
            return cls.objects.select_related("user").get(
                key_hash=key_hash,
                is_active=True,
            )
        except cls.DoesNotExist:
            return None

    def record_use(self) -> None:
        """Stamp last_used without a full model save."""
        APIKey.objects.filter(pk=self.pk).update(last_used=timezone.now())
        self.last_used = timezone.now()

    def revoke(self) -> None:
        """Deactivate this key immediately."""
        APIKey.objects.filter(pk=self.pk).update(is_active=False)
        self.is_active = False
        logger.info("APIKey revoked: %s (user=%s)", self.name, self.user.username)


class AuditAction(models.TextChoices):
    LOGIN = "login", "Login"
    LOGIN_FAILED = "login_failed", "Login Failed"
    LOGOUT = "logout", "Logout"
    REGISTER = "register", "Register"
    PASSWORD_CHANGE = "password_change", "Password Change"
    CONFIG_CHANGE = "config_change", "Config Change"
    TRADE_PAUSE = "trade_pause", "Trade Pause"
    TRADE_RESUME = "trade_resume", "Trade Resume"
    API_KEY_CREATED = "api_key_created", "API Key Created"
    API_KEY_REVOKED = "api_key_revoked", "API Key Revoked"
    PERMISSION_CHANGE = "permission_change", "Permission Change"
    TWO_FACTOR_ENABLED = "2fa_enabled", "2FA Enabled"
    TWO_FACTOR_DISABLED = "2fa_disabled", "2FA Disabled"


class AuditLog(models.Model):
    """
    Immutable security audit trail for all sensitive platform actions.

    Records are append-only; no update/delete should ever be applied.
    Supports nullable user FK to capture unauthenticated attempts
    (e.g. brute-force login failures from unknown IPs).
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        db_index=True,
        help_text="Null for unauthenticated or deleted-user events",
    )
    action = models.CharField(
        max_length=50,
        choices=AuditAction.choices,
        db_index=True,
    )
    ip_address = models.GenericIPAddressField(
        protocol="both",
        unpack_ipv4=True,
        null=True,
        blank=True,
        db_index=True,
    )
    user_agent = models.TextField(
        blank=True,
        default="",
    )
    details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Arbitrary structured context for the event (JSONB in PostgreSQL)",
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        editable=False,
    )

    class Meta:
        db_table = "audit_log"
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["action", "timestamp"], name="idx_auditlog_action_ts"),
            models.Index(fields=["user", "timestamp"], name="idx_auditlog_user_ts"),
            models.Index(fields=["ip_address", "timestamp"], name="idx_auditlog_ip_ts"),
        ]
        # Audit records must never be modified after creation
        default_permissions = ("add", "view")

    def __str__(self) -> str:
        actor = self.user.username if self.user else "anonymous"
        return f"[{self.timestamp:%Y-%m-%d %H:%M:%S}] {self.action} — {actor} @ {self.ip_address}"

    @classmethod
    def log(
        cls,
        action: str,
        user: User | None = None,
        ip_address: str | None = None,
        user_agent: str = "",
        details: dict | None = None,
    ) -> "AuditLog":
        """
        Convenience factory for creating audit records.

        Usage:
            AuditLog.log(
                action=AuditAction.LOGIN,
                user=request.user,
                ip_address="203.0.113.1",
                details={"username": "trader1"},
            )
        """
        entry = cls.objects.create(
            user=user,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent or "",
            details=details or {},
        )
        logger.info(
            "AUDIT %s | user=%s | ip=%s",
            action,
            user.username if user else "anon",
            ip_address,
        )
        return entry
