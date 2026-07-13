import sys
import pytest

from tuckit.core.models import Org
from tuckit.core.services.orgs import create_workspace


@pytest.fixture
def workspace(db):
    org = Org.objects.create(name="Test Org", slug="test-org")
    return create_workspace(org, "Test Workspace", slug="test-workspace")


@pytest.fixture
def asgi_app():
    """Provide a fresh ASGI app instance for each test with reloaded modules.

    This ensures the MCP session manager gets a fresh instance for each test,
    avoiding the "can only be called once per instance" error.
    """
    # Remove cached modules to force a fresh import
    # Only reload the ASGI entrypoint and the MCP server package (which owns the
    # session manager). Do NOT purge the Django app modules (tuckit.core /
    # tuckit.web) — that would unregister the apps and break the app registry.
    modules_to_remove = [key for key in sys.modules if key == "tuckit.asgi" or key.startswith("tuckit.core.mcp")]
    for mod in modules_to_remove:
        del sys.modules[mod]

    # Import fresh
    from tuckit.asgi import app
    yield app

    # Clean up after the test
    # Only reload the ASGI entrypoint and the MCP server package (which owns the
    # session manager). Do NOT purge the Django app modules (tuckit.core /
    # tuckit.web) — that would unregister the apps and break the app registry.
    modules_to_remove = [key for key in sys.modules if key == "tuckit.asgi" or key.startswith("tuckit.core.mcp")]
    for mod in modules_to_remove:
        del sys.modules[mod]
