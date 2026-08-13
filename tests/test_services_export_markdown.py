import io
import zipfile

import pytest
from django.utils import timezone

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.export.collect import Snapshot, collect
from tuckit.core.services.export.renderers import render_markdown_zip
from tuckit.core.services.slices import create_slice


@pytest.fixture
def org(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(email="owner@acme.com")
    OrgMember.objects.create(user=user, org=org, role="owner")
    area = create_area(org, "Backend", description="server side")
    s = create_slice(org, area=area, title="Export the data", spec="the design",
                     constraints="do not break this", tags=["blocker"])
    create_bite(s, "first step")
    create_slice(org, area=area, title="한국어만 있는 제목", spec="설계")
    create_slice(org, title="Unfiled capture")
    return org


def _zip(org):
    raw = render_markdown_zip(collect(org), exported_at=timezone.now())
    return zipfile.ZipFile(io.BytesIO(raw))


@pytest.mark.django_db
def test_tree_has_readme_areas_inbox_and_activity(org):
    names = set(_zip(org).namelist())
    assert "README.md" in names
    assert "activity.md" in names
    assert "areas/backend/_area.md" in names
    assert any(n.startswith("inbox/") for n in names)


@pytest.mark.django_db
def test_filed_slices_sit_under_their_area_slug(org):
    names = _zip(org).namelist()
    assert any(n.startswith("areas/backend/") and "export-the-data" in n
               for n in names)


@pytest.mark.django_db
def test_inbox_slices_sit_under_inbox(org):
    names = _zip(org).namelist()
    assert any(n.startswith("inbox/") and "unfiled-capture" in n for n in names)


@pytest.mark.django_db
def test_korean_only_title_falls_back_to_the_bare_ref_filename(org):
    """slugify() strips non-ASCII, and allow_unicode breaks zips on Windows."""
    names = _zip(org).namelist()
    korean = [n for n in names if n.endswith(f"{org.key}-2.md")]
    assert korean == ["areas/backend/" + f"{org.key}-2.md"]


@pytest.mark.django_db
def test_a_slice_file_contains_the_same_text_mcp_get_slice_returns(org):
    zf = _zip(org)
    path = next(n for n in zf.namelist() if "export-the-data" in n)
    body = zf.read(path).decode("utf-8")
    assert "# Export the data" in body
    assert "the design" in body
    assert "## Constraints" in body
    assert "do not break this" in body
    assert "## Steps" in body
    assert "- [ ] first step" in body


@pytest.mark.django_db
def test_a_slice_file_has_a_header_naming_its_ref_and_area(org):
    zf = _zip(org)
    path = next(n for n in zf.namelist() if "export-the-data" in n)
    head = zf.read(path).decode("utf-8").splitlines()[:12]
    joined = "\n".join(head)
    assert f"{org.key}-1" in joined
    assert "Backend" in joined


@pytest.mark.django_db
def test_readme_states_that_json_is_the_lossless_copy(org):
    body = _zip(org).read("README.md").decode("utf-8")
    assert "schema_version" in body
    assert "JSON" in body
    assert "Acme" in body


@pytest.mark.django_db
def test_empty_org_produces_exactly_a_readme_and_an_activity_file(db):
    """An org with no areas, slices or events still gets a constant tree
    shape: README.md plus activity.md (empty, but present — the README
    names activity.md unconditionally, so the zip must always contain it)."""
    empty = Org.objects.create(name="Empty", slug="empty")
    raw = render_markdown_zip(collect(empty), exported_at=timezone.now())
    names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
    assert names == ["README.md", "activity.md"]


@pytest.mark.django_db
def test_activity_file_is_written_even_with_zero_events(org):
    """A populated org (area + slice) can still have zero activity events if
    the log is cleared out from under it — e.g. by a retention policy, or
    (as constructed here) by deleting the rows create_slice()/create_bite()
    recorded, since there is no ordinary path that creates a slice without
    logging it. Deleting afterwards reads more clearly here than building
    ActivityEvent rows by hand, since the fixture already has slices whose
    ids the assertions below reuse.

    activity.md must still be written and say there is nothing in it, so the
    README's promise of the file — and its "(0 events)" count — stays true.
    """
    from tuckit.core.models import ActivityEvent

    ActivityEvent.objects.filter(org=org).delete()

    raw = render_markdown_zip(collect(org), exported_at=timezone.now())
    zf = zipfile.ZipFile(io.BytesIO(raw))
    assert "activity.md" in zf.namelist()
    body = zf.read("activity.md").decode("utf-8")
    assert "No activity recorded yet." in body


@pytest.mark.django_db
def test_rendering_the_zip_does_not_query_per_slice(org):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    snap = collect(org)
    with CaptureQueriesContext(connection) as q:
        render_markdown_zip(snap, exported_at=timezone.now())
    assert len(q) == 0, f"renderer queried the database: {[e['sql'] for e in q]}"


@pytest.mark.django_db
def test_markdown_zip_matches_render_slice_markdown_called_without_injection(db):
    """The renderer must build the exact same document render_slice_markdown()
    produces on its own default (query-based) path — not merely pass through
    whatever it is handed.

    render_slice_markdown(..., bites=, activity=) is a no-op transform by
    construction (bite 144's own test proves that much with byte-identical
    input/output for a single injected call). What it does NOT prove is that
    collect()'s org-wide, Python-grouped bites_by_slice / activity_by_slice
    produce the SAME ordering as the per-slice query path (list_bites() /
    slice_activity()). That equivalence currently holds because
    Bite.Meta.ordering == ["rank"] matches collect()'s
    order_by("slice_id", "rank"), and collect() re-sorts each activity group
    ascending by created_at to match slice_activity(). Nothing enforced that
    until this renderer became the first real consumer, so this test is the
    guard — several bites and several activity events, exercised through the
    real collect() snapshot rather than an injected stand-in.
    """
    from tuckit.core.services.activity import add_note
    from tuckit.core.services.state import render_slice_markdown

    org = Org.objects.create(name="Beta", slug="beta")
    user = User.objects.create(email="owner@beta.com")
    OrgMember.objects.create(user=user, org=org, role="owner")
    area = create_area(org, "Backend")
    s = create_slice(org, area=area, title="Multi-step work", spec="the design",
                     constraints="mind the gap")
    create_bite(s, "first step", body="details one")
    create_bite(s, "second step")
    create_bite(s, "third step", body="details three")
    add_note(s, "kicking this off")
    add_note(s, "still going")
    add_note(s, "almost there")

    zf = _zip(org)
    path = next(n for n in zf.namelist() if "multi-step-work" in n)
    from_zip = zf.read(path).decode("utf-8")

    slice_ = next(s2 for s2 in collect(org).slices if s2.id == s.id)
    # The zip's document has a header block the renderer prepends before
    # render_slice_markdown()'s own output; strip it so we compare only the
    # part that must be byte-identical to the no-injection call.
    from_direct = render_slice_markdown(slice_, with_activity=True)
    assert from_zip.endswith(from_direct)


@pytest.mark.django_db
def test_a_slice_whose_area_is_missing_from_the_snapshot_still_lands_somewhere(org):
    """render_markdown_zip buckets slices by area_id and only walks
    snapshot.areas plus the None bucket — a slice whose area_id names an area
    outside that list would otherwise be written nowhere, while README.md
    still counts it in "{n} slices".

    The ORM cannot produce this state: cross-org moves are refused and area
    deletion is SET_NULL, so a real slice's area_id always resolves within
    collect()'s own areas list or is None. Construct it directly on a
    Snapshot instead, bypassing collect(), to prove the renderer still files
    every slice somewhere rather than silently dropping the orphaned one.
    """
    real_snap = collect(org)
    stray_snap = Snapshot(
        org=real_snap.org,
        members=real_snap.members,
        areas=[],  # deliberately excludes "Backend", which two slices point at
        slices=real_snap.slices,
        bites=real_snap.bites,
        activity=real_snap.activity,
        bites_by_slice=real_snap.bites_by_slice,
        activity_by_slice=real_snap.activity_by_slice,
    )

    raw = render_markdown_zip(stray_snap, exported_at=timezone.now())
    names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
    slice_files = [n for n in names if n not in ("README.md", "activity.md")]

    assert len(slice_files) == len(real_snap.slices)
    assert all(n.startswith("inbox/") for n in slice_files)
