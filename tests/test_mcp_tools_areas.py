import pytest

from asgiref.sync import sync_to_async

from core.mcp.server import create_area, list_areas, list_tags
from core.models import Org, Workspace
from core.services.areas import create_area as svc_create_area
from core.services.slices import create_slice
from core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="P", slug="p")
    _, raw = generate_token(ws, "t")
    return ws, raw


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_and_list_areas():
    _ws, raw = await _seed()
    ctx = make_ctx(raw)
    created = await create_area(ctx, "Backend", "the api")
    assert created["slug"] == "backend"
    areas = await list_areas(ctx)
    assert [a["name"] for a in areas] == ["Backend"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_tags():
    ws, raw = await _seed()

    @sync_to_async
    def tag_it():
        area = svc_create_area(ws, "Backend")
        create_slice(area, "Auth", tags=["bug", "someday"])

    await tag_it()
    tags = await list_tags(make_ctx(raw))
    assert sorted(tags) == ["bug", "someday"]
