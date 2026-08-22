import json

import pytest
from django.utils import timezone

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.export.collect import collect
from tuckit.core.services.export.renderers import render_json
from tuckit.core.services.slices import create_slice

LONG_SPEC = "# Design\n\n" + ("Every byte of this must survive. " * 200)


@pytest.fixture
def org(db):
    org = Org.objects.create(name="Acme", slug="acme", description="we make things")
    user = User.objects.create(email="owner@acme.com")
    OrgMember.objects.create(user=user, org=org, role="owner")
    area = create_area(org, "Backend", description="server side")
    s = create_slice(org, area=area, title="한국어 제목 slice", spec=LONG_SPEC,
                     constraints="Do not break this.", tags=["bug"])
    create_bite(s, "first step", body="do the thing")
    create_slice(org, title="Unfiled capture")
    return org


def _dump(org):
    return json.loads(render_json(collect(org), exported_at=timezone.now()))


@pytest.mark.django_db
def test_envelope_carries_schema_version_and_org_identity(org):
    env = _dump(org)["tuckit_export"]
    assert env["schema_version"] == 1
    assert env["view"] == "full"
    assert env["org"] == {"slug": "acme", "name": "Acme", "key": org.key,
                          "description": "we make things",
                          "priority_policy": ""}
    assert "exported_at" in env


@pytest.mark.django_db
def test_the_envelope_carries_the_priority_policy_a_person_wrote(org):
    """The equality check above pins the envelope's shape with an unwritten
    policy, which is every org's starting state -- so on its own it would pass
    just as happily if the key were hardcoded to "". This pins the value.

    It matters because the policy is what makes each row's `priority` number
    readable. An export carrying the numbers without the sentences that define
    them hands back a ranking nobody can interpret.
    """
    org.priority_policy = "1 = money this week\n2 = a date promised outside"
    org.save(update_fields=["priority_policy", "updated_at"])

    assert _dump(org)["tuckit_export"]["org"]["priority_policy"] == (
        "1 = money this week\n2 = a date promised outside"
    )


@pytest.mark.django_db
def test_envelope_does_not_stamp_an_application_version(org):
    """pyproject's version has not moved in ~50 releases (TP-118)."""
    env = _dump(org)["tuckit_export"]
    assert "version" not in env
    assert "generator" not in env


@pytest.mark.django_db
def test_top_level_collections_are_flat(org):
    dump = _dump(org)
    assert set(dump) == {"tuckit_export", "members", "areas", "slices",
                         "bites", "activity"}
    # bites are their own collection, not nested inside slices
    assert "bites" not in dump["slices"][0]


@pytest.mark.django_db
def test_spec_and_constraints_survive_byte_for_byte(org):
    slice_row = next(s for s in _dump(org)["slices"] if s["spec"])
    assert slice_row["spec"] == LONG_SPEC
    assert slice_row["constraints"] == "Do not break this."
    assert slice_row["title"] == "한국어 제목 slice"


@pytest.mark.django_db
def test_slices_carry_the_derived_ref_and_stage(org):
    for row in _dump(org)["slices"]:
        assert row["ref"].startswith(f"{org.key}-")
        assert row["stage"] in {"needs_design", "needs_steps", "executing",
                                "ready_to_ship", "shipped", "dropped"}


@pytest.mark.django_db
def test_inbox_slices_are_present_with_a_null_area(org):
    unfiled = [s for s in _dump(org)["slices"] if s["title"] == "Unfiled capture"]
    assert len(unfiled) == 1
    assert unfiled[0]["area_id"] is None


@pytest.mark.django_db
def test_people_are_identified_by_email_not_id(org):
    assert _dump(org)["members"][0]["email"] == "owner@acme.com"


@pytest.mark.django_db
def test_rank_is_exported_so_order_can_be_restored(org):
    assert all(row["rank"] for row in _dump(org)["slices"])


@pytest.mark.django_db
def test_an_empty_org_renders_valid_json_not_an_error(db):
    empty = Org.objects.create(name="Empty", slug="empty")
    dump = json.loads(render_json(collect(empty), exported_at=timezone.now()))
    assert dump["slices"] == []
    assert dump["areas"] == []
    assert dump["tuckit_export"]["org"]["slug"] == "empty"


@pytest.mark.django_db
def test_output_is_utf8_bytes_with_readable_korean(org):
    raw = render_json(collect(org), exported_at=timezone.now())
    assert isinstance(raw, bytes)
    assert "한국어".encode() in raw  # ensure_ascii=False, so it is readable
