from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404
from django.urls import include, path, re_path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/", include("trading.urls")),
    path("api/ai/", include("ai.urls")),
]


def spa_view(request, resource=""):
    """Serve the React SPA — falls back to index.html for client-side routing."""
    spa_root = settings.FRONTEND_DIR
    file_path = spa_root / resource
    if resource and file_path.is_file():
        return FileResponse(open(file_path, "rb"))
    index = spa_root / "index.html"
    if index.is_file():
        return FileResponse(open(index, "rb"), content_type="text/html")
    raise Http404


urlpatterns += [
    re_path(r"^(?P<resource>.*)$", spa_view),
]
