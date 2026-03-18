"""WSGI config for FlockTrade."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "flocktrade.settings")
application = get_wsgi_application()
