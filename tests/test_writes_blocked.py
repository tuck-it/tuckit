"""A deployment can close writes for an org without hiding anything from it.

The point of these tests is not that writes fail — it is WHAT COMES BACK when
they do. A block that says nothing is indistinguishable from the product being
broken, and an agent that gets a bare status code will retry, give up, or
silently drop the work its human asked for. So every assertion here checks the
sentence, not just the exception type.
"""
import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from tuckit.core.entitlements import Entitlements
from tuckit.core.models import Area, Org, OrgMember, Slice, User
from tuckit.core.services.activity import add_note, latest_activity_id
from tuckit.core.services.areas import create_area, list_areas, update_area
from tuckit.core.services.bites import add_bites, create_bite, list_bites, update_bite
from tuckit.core.services.exceptions import WritesBlocked
from tuckit.core.services.slices import create_slice, list_slices, update_slice

REASON = (
    "Your 14-day trial ended on 29 Aug 2026. tuckit is read-only until you "
    "subscribe: https://app.tuckit.dev/cloud/upgrade"
)


def _blocked(org):
    return Entitlements(writes_blocked_reason=REASON)


def _allowed(org):
    return Entitlements()


BLOCK = override_settings(TUCKIT_ENTITLEMENTS_HOOK="tests.test_writes_blocked._blocked")
ALLOW = override_settings(TUCKIT_ENTITLEMENTS_HOOK="tests.test_writes_blocked._allowed")


@pytest.fixture
def seeded(db):
    """An org with content already in it — the realistic case. A blocked org is
    one that has been using the product, not an empty one."""
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(username="o@a.com", email="o@a.com")
    member = OrgMember.objects.create(user=user, org=org, role="owner")
    area = create_area(org, "Backend")
    slice_ = create_slice(org, area=area, title="Ship the thing")
    bite = create_bite(slice_, "First step")
    return org, user, member, area, slice_, bite


# --------------------------------------------------------------- the gate

@pytest.mark.django_db
def test_no_hook_means_writes_are_never_blocked(seeded):
    """Self-hosting configures no hook, so it must be unreachable by this code."""
    org, _u, _m, area, slice_, bite = seeded
    create_slice(org, area=area, title="another")
    update_slice(slice_, title="renamed")
    add_note(slice_, "a note")
    add_bites(slice_, [{"title": "b"}])
    update_bite(bite, status="done")
    update_area(area, name="Renamed")


@BLOCK
@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,call",
    [
        ("create_area", lambda ctx: create_area(ctx["org"], "New area")),
        ("update_area", lambda ctx: update_area(ctx["area"], name="Renamed")),
        ("create_slice", lambda ctx: create_slice(ctx["org"], title="New slice")),
        ("update_slice", lambda ctx: update_slice(ctx["slice"], title="Renamed")),
        ("add_note", lambda ctx: add_note(ctx["slice"], "a note")),
        ("add_bites", lambda ctx: add_bites(ctx["slice"], [{"title": "step"}])),
        ("create_bite", lambda ctx: create_bite(ctx["slice"], "step")),
        ("update_bite", lambda ctx: update_bite(ctx["bite"], status="done")),
    ],
)
def test_every_write_service_refuses_and_says_why(seeded, name, call):
    org, _u, _m, area, slice_, bite = seeded
    ctx = {"org": org, "area": area, "slice": slice_, "bite": bite}
    with pytest.raises(WritesBlocked) as exc:
        call(ctx)
    assert str(exc.value) == REASON, f"{name} refused without the reason"


@BLOCK
@pytest.mark.django_db
def test_the_reason_carries_what_a_person_needs_to_act(seeded):
    """Guards the shape of the message, not its exact wording: an agent relays
    this to its human, and 'blocked' alone leaves them with nowhere to go."""
    org, *_ = seeded
    with pytest.raises(WritesBlocked) as exc:
        create_slice(org, title="x")
    message = str(exc.value)
    assert "trial" in message.lower()
    assert "read-only" in message.lower()
    assert "http" in message, "no link to act on"


# --------------------------------------------------------------- reads survive

@BLOCK
@pytest.mark.django_db
def test_a_blocked_org_can_still_read_everything_it_has(seeded):
    """Nothing is deleted or hidden — that is promised in public on the pricing
    page, the terms and the refund policy."""
    org, _u, _m, area, slice_, _bite = seeded
    assert [a.name for a in list_areas(org)] == ["Backend"]
    assert [s.title for s in list_slices(area)] == ["Ship the thing"]
    assert [b.title for b in list_bites(slice_)] == ["First step"]
    assert Slice.objects.filter(org=org).count() == 1
    assert Area.objects.filter(org=org).count() == 1


@BLOCK
@pytest.mark.django_db
def test_a_blocked_org_can_still_export(seeded):
    """"Export everything whenever you like" is on the refund policy, so it has
    to keep working for exactly the org that stopped paying."""
    from tuckit.core.services.export.collect import collect

    org, *_ = seeded
    snapshot = collect(org)
    assert snapshot, "export produced nothing for a blocked org"


# --------------------------------------------------------------- not over-blocking

@ALLOW
@pytest.mark.django_db
def test_an_allowed_org_still_logs_what_it_did(seeded):
    """record_activity() must never be gated: every permitted write calls it to
    log itself, so gating it would make the activity log lie about operations
    that actually landed."""
    org, _u, _m, _area, slice_, _bite = seeded
    before = latest_activity_id(org)
    add_note(slice_, "still working")
    assert latest_activity_id(org) > before


@BLOCK
@pytest.mark.django_db
def test_registering_a_new_org_is_never_blocked():
    """A brand new org has no subscription row yet at the moment core creates
    it, and signing up must not depend on a billing lookup succeeding."""
    from tuckit.core.services.accounts import register

    _user, org = register(
        email="new@b.com", org_name="Fresh", slug="fresh", password="tuckit-seed-pw-9x2"
    )
    assert org.pk


# --------------------------------------------------------------- the MCP surface

@BLOCK
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_mcp_write_tools_hand_the_agent_the_sentence():
    """This is the whole reason for choosing an explanatory block over a silent
    one: the agent is the one that hits the wall, and it can only tell its human
    what it was told."""
    from tuckit.core.mcp.server import create_slice as mcp_create_slice
    from tuckit.core.services.tokens import generate_token
    from tests.test_mcp_tools_state import make_ctx

    @sync_to_async
    def _seed():
        org = Org.objects.create(name="Acme", slug="acme")
        _, raw = generate_token(org, "t")
        return raw

    raw = await _seed()
    with pytest.raises(WritesBlocked) as exc:
        await mcp_create_slice(make_ctx(raw), title="x")
    assert str(exc.value) == REASON


@BLOCK
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_mcp_read_tools_keep_working_while_writes_are_blocked():
    from tuckit.core.mcp.server import get_project_state
    from tuckit.core.services.tokens import generate_token
    from tests.test_mcp_tools_state import make_ctx

    @sync_to_async
    def _seed():
        org = Org.objects.create(name="Acme", slug="acme")
        _, raw = generate_token(org, "t")
        return raw

    raw = await _seed()
    state = await get_project_state(make_ctx(raw))
    assert "areas" in state


# --------------------------------------------------------------- the web surface

@BLOCK
@pytest.mark.django_db
def test_a_blocked_write_over_http_answers_with_the_reason_in_the_body(client, seeded):
    """402, and the sentence. The seat wall this replaces returned a bare
    'seat limit reached (3)' with no price, no explanation and no upgrade link;
    a status code with nothing behind it is the failure being designed out."""
    from django.urls import reverse

    org, user, _m, area, _slice, _bite = seeded
    client.force_login(user)
    resp = client.post(
        reverse("web:capture", args=[org.slug]),
        {"title": "from the web", "area_id": str(area.id)},
    )
    assert resp.status_code == 402
    assert resp.content.decode() == REASON
