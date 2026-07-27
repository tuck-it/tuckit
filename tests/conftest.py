import sys
import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice as _create_slice


@pytest.fixture
def org(db):
    return Org.objects.create(name="Test Org", slug="test-org")


@pytest.fixture
def area(org):
    return create_area(org, "Backend")


@pytest.fixture
def slice_(org, area):
    """area에 속한 슬라이스 하나. Task 6에서 create_slice의 시그니처가 바뀌면
    이 픽스처도 같이 바뀐다 — 그때까지는 모델을 직접 쓴다."""
    from tuckit.core.models import Slice
    from tuckit.core.services.slices import allocate_number
    return Slice.objects.create(
        org=org, area=area, title="테스트 슬라이스", spec="설계됨",
        rank="m", number=allocate_number(org),
    )


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
