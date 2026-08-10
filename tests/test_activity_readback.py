"""Guards for TP-108: the log says who acted, on every surface that shows it.

TP-101 started recording `member`; nothing read it back, so the change was
invisible. These tests assert the reading half — and in particular that no
surface falls through to "you" for someone else's work, which is the exact
misattribution the whole line of work exists to end.
"""

import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tuckit.core.models import ActivityEvent, Org, OrgMember
from tuckit.core.services.activity import who_label
from tuckit.core.services.areas import create_area
from tuckit.core.services.orgs import remove_member
from tuckit.core.services.slices import create_slice


@pytest.fixture
def pair(db):
    org = Org.objects.create(name="Acme", slug="acme")
    me = get_user_model().objects.create_user(email="me@a.com", password="pw123456")
    them = get_user_model().objects.create_user(email="them@a.com", password="pw123456")
    om_me = OrgMember.objects.create(user=me, org=org, role="owner")
    om_them = OrgMember.objects.create(user=them, org=org, role="member")
    return org, om_me, om_them


def _event(org, source, member, area=None):
    s = create_slice(org, area=area, title="X", source=source, member=member)
    return ActivityEvent.objects.filter(org=org).order_by("-id").first(), s


def _filed_event(org, source, member):
    """The detail template gates the whole activity thread on slice.area
    (_slice_detail.html:109), so an Inbox slice renders no thread at all —
    which would make a page-level assertion pass against an empty page."""
    area = create_area(org, "Backend")
    return _event(org, source, member, area=area)


# --- the labelling rule itself ------------------------------------------------


@pytest.mark.django_db
def test_your_own_work_reads_as_you(pair):
    org, me, _them = pair
    ev, _ = _event(org, "human", me)
    assert who_label(ev, viewer=me) == "you"


@pytest.mark.django_db
def test_your_own_agent_reads_as_agent(pair):
    """Unchanged from before: in the common single-person org, nothing gets noisier."""
    org, me, _them = pair
    ev, _ = _event(org, "agent", me)
    assert who_label(ev, viewer=me) == "agent"


@pytest.mark.django_db
def test_someone_elses_work_is_named(pair):
    org, me, them = pair
    ev, _ = _event(org, "human", them)
    assert who_label(ev, viewer=me) == "them@a.com"


@pytest.mark.django_db
def test_someone_elses_agent_is_named_as_theirs(pair):
    org, me, them = pair
    ev, _ = _event(org, "agent", them)
    assert who_label(ev, viewer=me) == "them@a.com (agent)"


@pytest.mark.django_db
def test_an_unattributed_human_row_is_never_you(pair):
    """Rows written before attribution existed. Falling through to "you" here
    is the original bug — a colleague's work showing as the reader's own."""
    org, me, _them = pair
    ev, _ = _event(org, "human", None)
    assert who_label(ev, viewer=me) == "someone"
    assert who_label(ev, viewer=me) != "you"


@pytest.mark.django_db
def test_an_unattributed_agent_row_reads_as_agent(pair):
    """A machine token has no user behind it; "agent" is the whole true answer."""
    org, me, _them = pair
    ev, _ = _event(org, "agent", None)
    assert who_label(ev, viewer=me) == "agent"


@pytest.mark.django_db
def test_no_viewer_shows_the_address_rather_than_claiming_you(pair):
    """The safe degradation: verbose, never wrong."""
    org, _me, them = pair
    ev, _ = _event(org, "human", them)
    assert who_label(ev, viewer=None) == "them@a.com"


@pytest.mark.django_db
def test_a_departed_colleague_still_has_a_name(pair):
    """TP-104 keeps the membership row, so history stays legible after they go."""
    org, me, them = pair
    ev, _ = _event(org, "human", them)
    remove_member(org, member=them)

    ev.refresh_from_db()
    assert who_label(ev, viewer=me) == "them@a.com"


# --- the surfaces -------------------------------------------------------------


def _actor_cells(html):
    """The rendered text of every activity-actor span on the page.

    Asserting against the whole page would pass on a page with no thread at
    all, which is exactly what the first version of these tests did.
    """
    cells = re.findall(r'<span class="activity-actor[^"]*">(.*?)</span>', html, re.S)
    return [c.strip() for c in cells]


@pytest.mark.django_db
def test_the_detail_thread_names_a_colleague(client, pair):
    org, me, them = pair
    _ev, s = _filed_event(org, "human", them)
    client.force_login(me.user)

    cells = _actor_cells(client.get(reverse("web:slice", args=[org.slug, s.id])).content.decode())
    assert cells, "no activity rows rendered — the assertion below would be vacuous"
    assert "them@a.com" in cells
    assert "you" not in cells, "a colleague's row must never read as the reader's own"


@pytest.mark.django_db
def test_the_detail_thread_still_says_you_for_your_own(client, pair):
    org, me, _them = pair
    _ev, s = _filed_event(org, "human", me)
    client.force_login(me.user)

    cells = _actor_cells(client.get(reverse("web:slice", args=[org.slug, s.id])).content.decode())
    assert cells, "no activity rows rendered"
    assert "you" in cells
    assert "me@a.com" not in cells, "your own row should not spell out your address"


@pytest.mark.django_db
def test_the_home_band_names_a_colleague(client, pair):
    """Home is the second render path for _activity_row and threads the viewer
    through a different function than the detail panel does."""
    org, me, them = pair
    _event(org, "human", them)
    client.force_login(me.user)

    # First load establishes the watermark; the band shows what came before it.
    client.get(reverse("web:home", args=[org.slug]))
    _event(org, "agent", them)
    cells = _actor_cells(client.get(reverse("web:home", args=[org.slug])).content.decode())

    assert cells, "the Home activity band rendered no rows"
    assert "you" not in cells, "someone else's rows must not read as the reader's own"
    assert any("them@a.com" in c for c in cells)


@pytest.mark.django_db
def test_the_live_payload_carries_the_person(client, pair):
    org, me, them = pair
    _event(org, "agent", them)
    client.force_login(me.user)

    rows = client.get(reverse("web:live", args=[org.slug]) + "?since=0").json()["events"]
    assert rows, "the live endpoint returned nothing to check"
    assert rows[0]["member"] == "them@a.com"
    assert rows[0]["source"] == "agent", "source must still say how it arrived"


@pytest.mark.django_db
def test_the_live_payload_says_null_when_nobody_is_known(client, pair):
    org, me, _them = pair
    _event(org, "agent", None)
    client.force_login(me.user)

    rows = client.get(reverse("web:live", args=[org.slug]) + "?since=0").json()["events"]
    assert rows[0]["member"] is None


@pytest.mark.django_db
def test_the_mcp_serializer_exposes_the_person(pair):
    from tuckit.core.mcp.serializers import activity_event_dict

    org, _me, them = pair
    ev, _ = _event(org, "agent", them)

    d = activity_event_dict(ev)
    assert d["member"] == "them@a.com", "an agent still cannot read who acted"
    assert d["source"] == "agent"


@pytest.mark.django_db
def test_the_mcp_serializer_says_null_for_a_machine_token(pair):
    from tuckit.core.mcp.serializers import activity_event_dict

    org, _me, _them = pair
    ev, _ = _event(org, "agent", None)

    assert activity_event_dict(ev)["member"] is None


@pytest.mark.django_db
def test_the_member_shape_matches_how_slices_express_a_person(pair):
    """An email string, like slice_dict's assignee — so a value read off the log
    can be handed straight back to a write tool without translation."""
    from tuckit.core.mcp.serializers import activity_event_dict, slice_dict

    org, _me, them = pair
    ev, s = _event(org, "agent", them)
    s.assignee = them
    s.save(update_fields=["assignee"])

    assert activity_event_dict(ev)["member"] == slice_dict(s)["assignee"]
