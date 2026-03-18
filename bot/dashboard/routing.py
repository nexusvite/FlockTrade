"""
dashboard/routing.py

WebSocket URL routing for the FlockTrade dashboard.

This module is imported by ``flocktrade/asgi.py`` which wires it into the
``ProtocolTypeRouter`` under the ``"websocket"`` key.  All WebSocket paths
defined here are wrapped in ``AuthMiddlewareStack`` by the ASGI config,
though ``LiveFeedConsumer`` performs its own JWT token authentication (via
the query-string ``?token=`` parameter) because browser WebSocket APIs do
not support custom HTTP headers during the initial handshake.

URL map
-------
Pattern                 Consumer                Purpose
----------------------  ----------------------  -----------------------------
ws/live/                LiveFeedConsumer        Real-time dashboard feed
"""

from django.urls import re_path

from .consumers import LiveFeedConsumer

websocket_urlpatterns = [
    # Matches:  ws://host/ws/live/
    #           wss://host/ws/live/
    # The trailing slash is optional to accommodate both browser clients and
    # test harnesses that may omit it.
    re_path(r"^ws/live/?$", LiveFeedConsumer.as_asgi()),
]
