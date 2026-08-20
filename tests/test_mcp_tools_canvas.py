import json
import types
from urllib.parse import urlsplit

import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from tuckit.core.mcp.server import create_slice, propose, update_slice
from tuckit.core.models import CanvasWatch, Org, Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.tokens import generate_token
from tuckit.core.services.watches import hash_watch_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed():
    org = Org.objects.create(name="Acme", slug="acme")
    _, raw = generate_token(org, "t")
    return org, raw, create_area(org, "Backend").id


@sync_to_async
def _draft_ids(slice_id):
    return [n["id"] for n in Slice.objects.get(id=slice_id).draft.get("nodes", [])]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_propose_puts_nodes_on_the_canvas():
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "Canvas", area_id=area_id)

    out = await propose(ctx, s["id"], [
        {"id": "q1", "parent": None, "kind": "question", "title": "Where does it live?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "On the slice",
         "summary": "one field, no new model", "recommended": True},
    ])

    assert out["count"] == 2
    assert out["node_ids"] == ["q1", "o1"]
    assert await _draft_ids(s["id"]) == ["q1", "o1"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_writing_the_spec_over_mcp_retires_the_canvas():
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "Canvas", area_id=area_id)
    await propose(ctx, s["id"], [
        {"id": "q1", "parent": None, "kind": "question", "title": "Q"}])

    await update_slice(ctx, s["id"], spec="## Decision\nOn the slice.")

    assert await _draft_ids(s["id"]) == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_propose_refuses_once_the_design_is_written():
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "Canvas", area_id=area_id, spec="## Done\ntext")

    with pytest.raises(InvalidValue):
        await propose(ctx, s["id"], [
            {"id": "q1", "parent": None, "kind": "note", "title": "Q"}])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_propose_hands_back_a_watch_url_for_a_question():
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "Canvas", area_id=area_id)

    out = await propose(ctx, s["id"], [
        {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "Left"},
    ])

    watch = await sync_to_async(CanvasWatch.objects.get)()
    # The URL carries the RAW token, and only its hash is stored -- so the
    # stored row must not contain the string that was handed out.
    token = out["watch_url"].rsplit("/", 1)[-1]
    assert token and token not in watch.token_hash
    assert watch.token_hash == hash_watch_token(token)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_batch_with_no_question_gets_no_watch():
    """Nothing to wait for, so no row and no URL. An unused watch is litter,
    and a URL that can only ever say "waiting" is worse than none."""
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "Canvas", area_id=area_id)

    out = await propose(ctx, s["id"], [
        {"id": "n1", "parent": None, "kind": "note", "title": "Context"},
    ])

    assert out["watch_url"] == ""
    assert await sync_to_async(CanvasWatch.objects.count)() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_watch_url_actually_resolves(client):
    """The URL is assembled in one place and consumed in another. A test that
    only checked the string's shape would pass while the path 404s."""
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    s = await create_slice(ctx, "Canvas", area_id=area_id)

    # Match the request's Host the Django test client sends, so the resolved
    # origin actually points back at the client that is about to poll it.
    with override_settings(TUCKIT_OAUTH_ISSUER="http://testserver"):
        out = await propose(ctx, s["id"], [
            {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        ])

    # Absolute -> path, so the Django test client can fetch it.
    scheme, _, rest = out["watch_url"].partition("://")
    assert scheme in ("http", "https")
    path = "/" + rest.split("/", 1)[1]

    res = await sync_to_async(client.get)(path)

    assert res.status_code == 200
    assert json.loads(res.content) == {"status": "waiting"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_watch_url_resolves_without_an_issuer_pin(client):
    """`_public_origin`'s other branch: no TUCKIT_OAUTH_ISSUER set, so the
    origin is derived from the request itself -- what a self-hosted install
    needs. The test above only exercises the pinned branch (its origin never
    touches the request-derived code path); this one has to prove the derived
    branch produces a fetchable URL too, with the right scheme -- an
    un-proxied host has no `x-forwarded-proto`, so a wrong fallback to
    "https" would silently hand back a URL that never resolves."""
    _org, raw, area_id = await _seed()
    ctx = make_ctx(raw)
    # A bare, un-proxied request: no x-forwarded-proto, but the request
    # itself knows its own (plain HTTP) scheme -- like a starlette Request's
    # `.url.scheme` on a self-hosted install with no reverse proxy in front.
    ctx.request_context.request.headers["host"] = "testserver"
    ctx.request_context.request.url = types.SimpleNamespace(scheme="http")
    s = await create_slice(ctx, "Canvas", area_id=area_id)

    with override_settings(TUCKIT_OAUTH_ISSUER=""):
        out = await propose(ctx, s["id"], [
            {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        ])

    # Check scheme, host and path explicitly -- not just the token off the
    # tail, which stays parseable even when the origin has degraded (e.g. to
    # "https:" with no host, per the bug this test was added to catch).
    parts = urlsplit(out["watch_url"])
    assert parts.scheme == "http"
    assert parts.netloc == "testserver"
    assert parts.path.startswith("/watch/")

    res = await sync_to_async(client.get)(parts.path)

    assert res.status_code == 200
    assert json.loads(res.content) == {"status": "waiting"}
