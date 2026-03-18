"""Celery configuration for FlockTrade."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "flocktrade.settings")

app = Celery("flocktrade")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
