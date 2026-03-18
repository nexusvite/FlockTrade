"""
accounts/admin.py

Django admin registrations for the accounts app.

Provides:
  - UserProfileAdmin  — inline on User admin + standalone list
  - APIKeyAdmin       — key management with revoke action
  - AuditLogAdmin     — immutable read-only security log
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.html import format_html

from .models import APIKey, AuditLog, UserProfile


# ---------------------------------------------------------------------------
# UserProfile — inline and standalone admin
# ---------------------------------------------------------------------------


class UserProfileInline(admin.StackedInline):
    """Embeds the UserProfile form inside the standard User admin page."""

    model = UserProfile
    can_delete = False
    verbose_name = "FlockTrade Profile"
    verbose_name_plural = "FlockTrade Profile"
    fields = (
        "role",
        "telegram_chat_id",
        "notification_enabled",
        "two_factor_enabled",
        "last_active",
    )
    readonly_fields = ("last_active",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user_link",
        "role_badge",
        "telegram_chat_id",
        "notification_enabled",
        "two_factor_enabled",
        "last_active",
        "created_at",
    )
    list_filter = ("role", "notification_enabled", "two_factor_enabled")
    search_fields = ("user__username", "user__email", "telegram_chat_id")
    readonly_fields = ("id", "created_at", "updated_at", "last_active")
    ordering = ("-created_at",)

    fieldsets = (
        (
            "Identity",
            {
                "fields": ("id", "user"),
            },
        ),
        (
            "Access Control",
            {
                "fields": ("role",),
            },
        ),
        (
            "Notifications",
            {
                "fields": ("telegram_chat_id", "notification_enabled"),
            },
        ),
        (
            "Security",
            {
                "fields": ("two_factor_enabled",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("last_active", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="User")
    def user_link(self, obj: UserProfile):
        url = f"/admin/auth/user/{obj.user_id}/change/"
        return format_html('<a href="{}">{}</a>', url, obj.user.username)

    @admin.display(description="Role")
    def role_badge(self, obj: UserProfile) -> str:
        colours = {
            "admin": "#dc3545",
            "trader": "#0d6efd",
            "viewer": "#6c757d",
        }
        colour = colours.get(obj.role, "#6c757d")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:600;">{}</span>',
            colour,
            obj.get_role_display(),
        )


# ---------------------------------------------------------------------------
# Extend the default User admin with the profile inline
# ---------------------------------------------------------------------------


class CustomUserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "profile_role",
        "date_joined",
    )

    @admin.display(description="Role")
    def profile_role(self, obj: User) -> str:
        try:
            return obj.profile.get_role_display()
        except UserProfile.DoesNotExist:
            return "—"


# Re-register User with the extended admin
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


# ---------------------------------------------------------------------------
# APIKey admin
# ---------------------------------------------------------------------------


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user_link",
        "permissions",
        "is_active",
        "is_valid_display",
        "last_used",
        "expires_at",
        "created_at",
    )
    list_filter = ("permissions", "is_active")
    search_fields = ("name", "user__username")
    readonly_fields = ("id", "key_hash", "created_at", "last_used")
    ordering = ("-created_at",)
    actions = ["revoke_keys"]

    fieldsets = (
        (
            "Key Details",
            {
                "fields": ("id", "user", "name", "permissions"),
            },
        ),
        (
            "Security",
            {
                "fields": ("key_hash", "is_active", "expires_at"),
                "description": "The raw API key is never stored. Only the SHA-256 hash is shown.",
            },
        ),
        (
            "Usage",
            {
                "fields": ("last_used", "created_at"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="User")
    def user_link(self, obj: APIKey):
        url = f"/admin/auth/user/{obj.user_id}/change/"
        return format_html('<a href="{}">{}</a>', url, obj.user.username)

    @admin.display(description="Valid", boolean=True)
    def is_valid_display(self, obj: APIKey) -> bool:
        return obj.is_valid

    @admin.action(description="Revoke selected API keys")
    def revoke_keys(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} API key(s) revoked.")


# ---------------------------------------------------------------------------
# AuditLog admin — strictly read-only
# ---------------------------------------------------------------------------


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "timestamp",
        "action_badge",
        "user_link",
        "ip_address",
        "user_agent_short",
    )
    list_filter = ("action",)
    search_fields = ("user__username", "ip_address", "action")
    readonly_fields = (
        "id",
        "user",
        "action",
        "ip_address",
        "user_agent",
        "details",
        "timestamp",
    )
    ordering = ("-timestamp",)
    date_hierarchy = "timestamp"

    # Audit records are immutable — disable add/change/delete
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="User")
    def user_link(self, obj: AuditLog):
        if not obj.user:
            return format_html('<em style="color:#999;">anonymous</em>')
        url = f"/admin/auth/user/{obj.user_id}/change/"
        return format_html('<a href="{}">{}</a>', url, obj.user.username)

    @admin.display(description="Action")
    def action_badge(self, obj: AuditLog) -> str:
        colours = {
            "login": "#198754",
            "login_failed": "#dc3545",
            "logout": "#6c757d",
            "register": "#0d6efd",
            "password_change": "#fd7e14",
            "config_change": "#6610f2",
            "trade_pause": "#ffc107",
            "trade_resume": "#20c997",
            "api_key_created": "#0dcaf0",
            "api_key_revoked": "#dc3545",
            "permission_change": "#6610f2",
            "2fa_enabled": "#198754",
            "2fa_disabled": "#dc3545",
        }
        colour = colours.get(obj.action, "#6c757d")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:600;">{}</span>',
            colour,
            obj.get_action_display(),
        )

    @admin.display(description="User Agent")
    def user_agent_short(self, obj: AuditLog) -> str:
        ua = obj.user_agent
        if len(ua) > 60:
            return ua[:57] + "..."
        return ua
