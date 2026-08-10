"""Guards for TP-101: the activity log records WHO was acting.

`source` says how a write arrived (human|agent). `member` says who
was behind it. The two are different questions, and the bug this fixes was
answering only the first — two people in one org each running Claude Code were
indistinguishable, every row reading `source="agent"` and nothing else.

The write paths are enumerated rather than sampled, the same shape TP-104's
gate test uses: the failure mode here is a path nobody threaded, and a test
that exercises one MCP tool and one view proves nothing about the other twelve.
"""

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.urls import reverse

from tuckit.core.mcp.server import (
    add_bites as mcp_add_bites,
    add_note as mcp_add_note,
    create_area as mcp_create_area,
    create_slice as mcp_create_slice,
    update_bite as mcp_update_bite,
    update_slice as mcp_update_slice,
)
from tuckit.core.models import ActivityEvent, Org, OrgMember
from tuckit.core.services import oauth
from tuckit.core.services.areas import create_area
from tuckit.core.services.orgs import remove_member
from tuckit.core.services.slices import create_slice, set_slice_status
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


def _latest(org):
    return ActivityEvent.objects.filter(org=org).order_by("-id").first()


# --- the model keeps the two axes apart --------------------------------------


@pytest.mark.django_db
def test_source_and_member_are_separate_axes(db):
    """An agent acting for a person records BOTH: channel and identity."""
    org = Org.objects.create(name="Acme", slug="acme")
    user = get_user_model().objects.create_user(email="h@a.com", password="pw123456")
    om = OrgMember.objects.create(user=user, org=org, role="owner")

    create_slice(org, area=None, title="Agent wrote this", source="agent", member=om)

    ev = _latest(org)
    assert ev.source == "agent", "the channel is still recorded, unchanged"
    assert ev.member_id == om.pk, "and now so is the person who was driving"


@pytest.mark.django_db
def test_member_is_optional_and_absence_is_not_an_error(db):
    """Legacy ApiToken callers have no user; those rows stay unattributed."""
    org = Org.objects.create(name="Acme", slug="acme")
    create_slice(org, area=None, title="Headless", source="agent")

    ev = _latest(org)
    assert ev.member_id is None
    assert ev.source == "agent"


@pytest.mark.django_db
def test_leaving_the_org_does_not_erase_the_attribution(db):
    """The TP-104 guarantee this slice is built on. If OrgMember were still
    hard-deleted, SET_NULL would blank this row the moment they left."""
    org = Org.objects.create(name="Acme", slug="acme")
    user = get_user_model().objects.create_user(email="leaver@a.com", password="pw123456")
    OrgMember.objects.create(user=get_user_model().objects.create_user(
        email="owner@a.com", password="pw123456"), org=org, role="owner")
    om = OrgMember.objects.create(user=user, org=org, role="member")
    create_slice(org, area=None, title="Theirs", source="human", member=om)

    remove_member(org, member=om)

    ev = _latest(org)
    assert ev.member_id == om.pk
    assert ev.member.user.email == "leaver@a.com"


# --- `source` must keep working exactly as before -----------------------------


@pytest.mark.django_db
def test_source_still_drives_the_agent_only_reads(db):
    """onboarding's "connected" check and active_targets read source alone.
    Adding `member` must not have moved that signal."""
    from tuckit.core.services.activity import active_targets
    from tuckit.core.services.onboarding import onboarding_state

    org = Org.objects.create(name="Acme", slug="acme")
    user = get_user_model().objects.create_user(email="h@a.com", password="pw123456")
    om = OrgMember.objects.create(user=user, org=org, role="owner")

    create_slice(org, area=None, title="By a human", source="human", member=om)
    assert onboarding_state(org).connected is False, "a human write is not 'agent connected'"
    assert active_targets(org) == {}

    s = create_slice(org, area=None, title="By an agent", source="agent", member=om)
    assert onboarding_state(org).connected is True
    assert s.id in active_targets(org), "heat still keys off source, not member"


@pytest.mark.django_db
def test_source_values_are_still_only_human_and_agent(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = get_user_model().objects.create_user(email="h@a.com", password="pw123456")
    om = OrgMember.objects.create(user=user, org=org, role="owner")
    s = create_slice(org, area=None, title="X", source="human", member=om)
    set_slice_status(s, "shipped", member=om)
    create_area(org, "Backend", source="agent", member=om)

    assert set(ActivityEvent.objects.filter(org=org).values_list("source", flat=True)) <= {"human", "agent"}


# --- every MCP write path, enumerated ----------------------------------------


@sync_to_async
def _seed_oauth():
    org = Org.objects.create(name="Acme", slug="acme")
    user = get_user_model().objects.create_user(email="human@example.com", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    client = oauth.create_client("cli", ["http://localhost/cb"])
    access, _refresh, _ttl = oauth.issue_tokens(client, user, org, "mcp")
    return org.id, access


@sync_to_async
def _seed_machine():
    org = Org.objects.create(name="Acme", slug="acme")
    _, raw = generate_token(org, "t")
    return org.id, raw


@sync_to_async
def _attributions(org_id):
    """(verb, source, member email or None) for every row, oldest first."""
    return [
        (e.verb, e.source, e.member.user.email if e.member_id else None)
        for e in ActivityEvent.objects.filter(org_id=org_id).select_related("member__user").order_by("id")
    ]


async def _exercise_every_writing_tool(token):
    """Drive all six MCP tools that append to the activity log."""
    ctx = make_ctx(token)
    area = await mcp_create_area(ctx, "Backend")                       # created (area)
    s = await mcp_create_slice(ctx, "A slice")                         # created (slice)
    await mcp_add_note(ctx, s["id"], "a note")                         # noted
    await mcp_update_slice(ctx, s["id"], status="shipped")             # shipped
    await mcp_update_slice(ctx, s["id"], area_id=area["id"])           # moved
    made = await mcp_add_bites(ctx, s["id"], [{"title": "step one"}])  # created (bite)
    await mcp_update_bite(ctx, made[0]["id"], status="done")           # status_changed
    return s, area


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_every_mcp_write_records_the_oauth_caller():
    org_id, access = await _seed_oauth()
    await _exercise_every_writing_tool(access)

    rows = await _attributions(org_id)
    assert rows, "the tools recorded nothing at all"
    unattributed = [r for r in rows if r[2] is None]
    assert not unattributed, f"these MCP writes name nobody: {unattributed}"
    assert {r[1] for r in rows} == {"agent"}, "source must still say how it arrived"
    assert {r[2] for r in rows} == {"human@example.com"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_every_mcp_write_survives_a_machine_token():
    """No user to name, and that must not raise — just an unattributed row."""
    org_id, raw = await _seed_machine()
    await _exercise_every_writing_tool(raw)

    rows = await _attributions(org_id)
    assert rows
    assert {r[2] for r in rows} == {None}
    assert {r[1] for r in rows} == {"agent"}


# --- the web write paths ------------------------------------------------------


@pytest.fixture
def web_org(db):
    from tuckit.core.management.commands.bootstrap import ensure_bootstrap
    org, _ = ensure_bootstrap()
    return org


@pytest.fixture
def web_client(client, web_org):
    user = get_user_model().objects.get(email="local@tuckit.local")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_web_capture_records_the_logged_in_person(web_client, web_org):
    web_client.post(reverse("web:capture", args=[web_org.slug]), {"title": "Typed by hand"})

    ev = _latest(web_org)
    assert ev.verb == "created"
    assert ev.source == "human"
    assert ev.member is not None, "a human click must name the human"
    assert ev.member.user.email == "local@tuckit.local"


@pytest.mark.django_db
def test_web_status_change_records_the_logged_in_person(web_client, web_org):
    s = create_slice(web_org, area=None, title="X")
    web_client.post(reverse("web:slice_status", args=[web_org.slug, s.id]), {"status": "shipped"})

    ev = _latest(web_org)
    assert ev.verb == "shipped"
    assert ev.member is not None and ev.member.user.email == "local@tuckit.local"


@pytest.mark.django_db
def test_web_bite_paths_record_the_logged_in_person(web_client, web_org):
    """bite_create/bite_toggle resolve from a bite id and never had an org in
    scope — exactly the views most likely to be left unthreaded."""
    s = create_slice(web_org, area=None, title="X")
    web_client.post(reverse("web:bite_create", args=[web_org.slug, s.id]), {"title": "step"})
    created = _latest(web_org)
    assert created.verb == "created" and created.target_type == "bite"
    assert created.member is not None, "bite_create did not name anyone"

    bite_id = created.target_id
    web_client.post(reverse("web:bite_toggle", args=[web_org.slug, bite_id]))
    toggled = _latest(web_org)
    assert toggled.target_type == "bite" and toggled.id != created.id
    assert toggled.member is not None, "bite_toggle did not name anyone"
    assert toggled.member.user.email == "local@tuckit.local"


@pytest.mark.django_db
def test_web_area_paths_record_the_logged_in_person(web_client, web_org):
    web_client.post(reverse("web:area_create", args=[web_org.slug]), {"name": "Frontend"})

    ev = _latest(web_org)
    assert ev.verb == "created" and ev.target_type == "area"
    assert ev.member is not None and ev.member.user.email == "local@tuckit.local"
