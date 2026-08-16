"""ASGI entrypoint for the open-source app: MCP under "/mcp", Django elsewhere.

The composition itself lives in `tuckit.core.mcp.compose`, not here, so that
every entrypoint (this one, and the cloud layer's) builds the same app from the
same source instead of maintaining copies that drift -- see that module for the
two production outages that motivated it. Keep this file limited to booting
Django with *its* settings module and handing the result to the factory.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tuckit.settings")

from django.core.asgi import get_asgi_application

# get_asgi_application() triggers django.setup(); import model-touching modules AFTER it.
django_asgi_app = get_asgi_application()

from tuckit.core.mcp.compose import build_asgi_app  # noqa: E402

app = build_asgi_app(django_asgi_app)
