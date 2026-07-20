"""The global capture modal is a full slice-authoring form: Title is required,
everything else (area, status, spec, tags) is optional. Submitting a title
alone stays a quick, unfiled Inbox capture — it becomes a Ticket, since there's
no more Inbox Area to place a Slice in. Filling in an area (with or without
other detail) creates a complete Slice and redirects the user into it. Bites
are no longer authored from capture — they live under a Slice's Plan section."""
import pytest

from tuckit.core.models import Slice, Ticket
from tuckit.core.services.areas import create_area


P = lambda org: f"/{org.slug}"


@pytest.mark.django_db
def test_capture_title_only_stays_quick(client_local, org):
    """Title-only stays a quick, unfiled capture: a Ticket, 200 toast bundle, no redirect."""
    resp = client_local.post(f"{P(org)}/capture", {"title": "quick one"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert "HX-Redirect" not in resp
    t = Ticket.objects.get(title="quick one")
    assert t.area is None and t.status == "open"


@pytest.mark.django_db
def test_capture_rich_creates_full_slice_and_redirects(client_local, org):
    backend = create_area(org, "Backend")
    resp = client_local.post(f"{P(org)}/capture", {
        "title": "Payment integration",
        "area_id": backend.id,
        "spec": "Paddle webhook handling",
        "status": "planned",
        "tags": ["billing", "urgent"],
    }, HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    s = Slice.objects.get(title="Payment integration")
    assert s.spec == "Paddle webhook handling"
    assert s.status == "planned"
    assert {t.name for t in s.tags.all()} == {"billing", "urgent"}
    assert resp["HX-Redirect"].endswith(f"/slices/{s.id}/")


@pytest.mark.django_db
def test_capture_rich_into_explicit_area(client_local, org):
    backend = create_area(org, "Backend")
    resp = client_local.post(
        f"{P(org)}/capture", {"title": "in area", "area_id": backend.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 204
    s = Slice.objects.get(title="in area")
    assert s.area_id == backend.id
    assert "HX-Redirect" in resp


@pytest.mark.django_db
def test_capture_status_change_alone_is_rich(client_local, org):
    """Bumping the status off the default (planned) is enough to count as
    authoring — but authoring a Slice always needs an area now."""
    backend = create_area(org, "Backend")
    resp = client_local.post(
        f"{P(org)}/capture", {"title": "planned thing", "area_id": backend.id, "status": "building"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 204
    assert "HX-Redirect" in resp
    assert Slice.objects.get(title="planned thing").status == "building"


@pytest.mark.django_db
def test_capture_rich_without_area_requires_one(client_local, org):
    """Spec/tags/status alone (no area) can't create a Slice — there's no more
    magic Inbox area to fall back into — so it's rejected rather than silently
    dropping the authored detail."""
    resp = client_local.post(
        f"{P(org)}/capture", {"title": "no area", "status": "building"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 400
    assert not Slice.objects.filter(title="no area").exists()
    assert not Ticket.objects.filter(title="no area").exists()


@pytest.mark.django_db
def test_capture_requires_title(client_local, org):
    resp = client_local.post(
        f"{P(org)}/capture", {"title": "   ", "spec": "orphan"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 400
    assert not Slice.objects.filter(spec="orphan").exists()


@pytest.mark.django_db
def test_capture_invalid_status_400_creates_nothing(client_local, org):
    resp = client_local.post(
        f"{P(org)}/capture", {"title": "bad status", "status": "blocked"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 400
    assert not Slice.objects.filter(title="bad status").exists()


@pytest.mark.django_db
def test_capture_modal_renders_full_form(client_local, org):
    create_area(org, "Backend")
    body = client_local.get(f"{P(org)}/inbox/").content.decode()
    # required title + the optional authoring controls
    assert 'name="title"' in body
    assert 'name="area_id"' in body
    assert 'name="status"' in body
    assert 'name="spec"' in body
    assert 'capture-lbl">Spec<' in body        # field labelled Spec, not Description
    assert 'capture-lbl">Description<' not in body
    assert "Backend" in body            # workspace area offered in the Area select
    assert 'name="bite_titles"' not in body   # capture no longer authors bites


@pytest.mark.django_db
def test_capture_modal_renders_shared_fields(client_local, org):
    body = client_local.get(f"{P(org)}/inbox/").content.decode()
    # capture modal is always present in the shell; it includes the shared fields
    assert 'name="area_id"' in body
    assert 'name="status"' in body
    assert 'name="spec"' in body
