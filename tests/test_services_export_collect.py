import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.export.collect import collect, rows
from tuckit.core.services.slices import create_slice


def _org_with(n_slices, slug="acme"):
    org = Org.objects.create(name="Acme", slug=slug)
    user = User.objects.create(email=f"o@{slug}.com")
    OrgMember.objects.create(user=user, org=org, role="owner")
    area = create_area(org, "Backend")
    for i in range(n_slices):
        s = create_slice(org, area=area, title=f"Slice {i}", spec="designed",
                         tags=["alpha", "beta"])
        create_bite(s, "step one")
        create_bite(s, "step two")
    # One Inbox slice: no area. The export must not lose these.
    create_slice(org, title="Unfiled capture")
    return org


@pytest.mark.django_db
def test_collect_includes_inbox_slices():
    org = _org_with(2)
    snap = collect(org)
    titles = [s.title for s in snap.slices]
    assert "Unfiled capture" in titles
    assert len(snap.slices) == 3


@pytest.mark.django_db
def test_slices_keep_rank_order_after_annotation():
    """annotate() drops Meta.ordering. sqlite hides it; Postgres does not."""
    org = _org_with(5)
    snap = collect(org)
    ranks = [s.rank for s in snap.slices]
    assert ranks == sorted(ranks)


@pytest.mark.django_db
def test_bite_counts_are_not_multiplied_by_the_tags_join():
    """Without distinct=True the tags join fans rows out and doubles the counts."""
    org = _org_with(1)
    snap = collect(org)
    filed = [s for s in snap.slices if s.area_id is not None]
    assert filed[0].export_bites_total == 2
    assert filed[0].export_bites_done == 0


@pytest.mark.django_db
def test_query_count_does_not_grow_with_the_number_of_slices():
    small = _org_with(2, slug="small")
    big = _org_with(40, slug="big")
    with CaptureQueriesContext(connection) as q_small:
        collect(small)
    with CaptureQueriesContext(connection) as q_big:
        collect(big)
    assert len(q_big) == len(q_small), (
        f"collect() is N+1: {len(q_small)} queries for 2 slices, "
        f"{len(q_big)} for 40"
    )


@pytest.mark.django_db
def test_rows_applies_the_schema_extractors():
    org = _org_with(1)
    snap = collect(org)
    row = next(r for r in rows(snap, "slices") if r["title"] == "Slice 0")
    assert row["ref"].endswith("-1") or row["ref"].endswith("-2")
    assert row["stage"] == "executing"
    assert row["tags"] == ["alpha", "beta"]
    assert row["spec"] == "designed"


@pytest.mark.django_db
def test_ended_membership_still_resolves_to_an_email():
    """OrgMember.objects hides ended rows; authorship must not export as null."""
    from django.utils import timezone
    org = _org_with(1)
    leaver = User.objects.create(email="gone@acme.com")
    m = OrgMember.objects.create(user=leaver, org=org, role="member")
    s = create_slice(org, title="By someone who left", created_by=m)
    m.ended_at = timezone.now()
    m.save(update_fields=["ended_at"])

    snap = collect(org)
    row = next(r for r in rows(snap, "slices") if r["id"] == s.id)
    assert row["created_by"] == "gone@acme.com"
    assert "gone@acme.com" in [r["email"] for r in rows(snap, "members")]
