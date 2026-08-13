import io
import zipfile

import pytest
from django.utils import timezone

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.export.collect import collect
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
def test_empty_org_produces_a_zip_with_just_the_readme(db):
    empty = Org.objects.create(name="Empty", slug="empty")
    raw = render_markdown_zip(collect(empty), exported_at=timezone.now())
    names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
    assert "README.md" in names
    assert not any(n.startswith("areas/") for n in names)


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
