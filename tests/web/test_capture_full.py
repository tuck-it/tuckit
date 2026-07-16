"""The global capture modal is a full slice-authoring form: Title is required,
everything else (area, status, spec, tags) is optional. Submitting a title
alone stays a quick Inbox capture; filling any optional field creates a
complete slice and redirects the user into it. Bites are no longer authored
from capture — they live under a Slice's Plan section."""
import pytest

from tuckit.core.models import Slice
from tuckit.core.services.areas import create_area, get_or_create_triage


P = lambda ws: f"/{ws.org.slug}/{ws.slug}"


@pytest.mark.django_db
def test_capture_title_only_stays_quick(client_local, workspace):
    """Title-only keeps today's behavior: Inbox/idea, 200 toast bundle, no redirect."""
    get_or_create_triage(workspace)
    resp = client_local.post(f"{P(workspace)}/capture", {"title": "quick one"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert "HX-Redirect" not in resp
    s = Slice.objects.get(title="quick one")
    assert s.area.is_triage and s.status == "idea"


@pytest.mark.django_db
def test_capture_rich_creates_full_slice_and_redirects(client_local, workspace):
    resp = client_local.post(f"{P(workspace)}/capture", {
        "title": "결제 연동",
        "spec": "Paddle webhook 처리",
        "status": "planned",
        "tags": ["billing", "urgent"],
    }, HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    s = Slice.objects.get(title="결제 연동")
    assert s.spec == "Paddle webhook 처리"
    assert s.status == "planned"
    assert {t.name for t in s.tags.all()} == {"billing", "urgent"}
    assert resp["HX-Redirect"].endswith(f"/slices/{s.id}/")


@pytest.mark.django_db
def test_capture_rich_into_explicit_area(client_local, workspace):
    backend = create_area(workspace, "Backend")
    resp = client_local.post(
        f"{P(workspace)}/capture", {"title": "in area", "area_id": backend.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 204
    s = Slice.objects.get(title="in area")
    assert s.area_id == backend.id
    assert "HX-Redirect" in resp


@pytest.mark.django_db
def test_capture_status_change_alone_is_rich(client_local, workspace):
    """Bumping the status off the default (idea) is enough to count as authoring."""
    resp = client_local.post(
        f"{P(workspace)}/capture", {"title": "planned thing", "status": "building"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 204
    assert "HX-Redirect" in resp
    assert Slice.objects.get(title="planned thing").status == "building"


@pytest.mark.django_db
def test_capture_requires_title(client_local, workspace):
    resp = client_local.post(
        f"{P(workspace)}/capture", {"title": "   ", "spec": "orphan"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 400
    assert not Slice.objects.filter(spec="orphan").exists()


@pytest.mark.django_db
def test_capture_invalid_status_400_creates_nothing(client_local, workspace):
    resp = client_local.post(
        f"{P(workspace)}/capture", {"title": "bad status", "status": "blocked"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 400
    assert not Slice.objects.filter(title="bad status").exists()


@pytest.mark.django_db
def test_capture_modal_renders_full_form(client_local, workspace):
    create_area(workspace, "Backend")
    body = client_local.get(f"{P(workspace)}/triage/").content.decode()
    # required title + the optional authoring controls
    assert 'name="title"' in body
    assert 'name="area_id"' in body
    assert 'name="status"' in body
    assert 'name="spec"' in body
    assert 'capture-lbl">Spec<' in body        # field labelled Spec, not Description
    assert 'capture-lbl">Description<' not in body
    assert "Backend" in body            # workspace area offered in the Area select
    assert 'name="bite_titles"' not in body   # capture no longer authors bites
