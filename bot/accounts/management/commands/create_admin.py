"""Management command to create initial admin user from environment variables."""
import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create initial admin user from ADMIN_USERNAME/EMAIL/PASSWORD env vars"

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME", "admin")
        email = os.environ.get("ADMIN_EMAIL", "admin@flocktrade.local")
        password = os.environ.get("ADMIN_PASSWORD", "")

        if not password:
            self.stderr.write("ADMIN_PASSWORD environment variable is not set.")
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Admin user '{username}' already exists, skipping.")
            return

        user = User.objects.create_superuser(
            username=username, email=email, password=password
        )

        # Create UserProfile with admin role
        from accounts.models import UserProfile

        UserProfile.objects.get_or_create(
            user=user,
            defaults={"role": "admin"},
        )

        self.stdout.write(self.style.SUCCESS(f"Admin user '{username}' created."))
