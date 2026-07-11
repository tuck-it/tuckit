import pytest
from tuckit.core.services.areas import create_area, get_or_create_inbox
from tuckit.core.services.slices import create_slice
from tuckit.core.models import Slice
from tuckit.core.models.org import Org
from tuckit.core.models.workspace import Workspace

@pytest.mark.django_db
def test_capture_lands_in_inbox_as_idea(client_local, workspace):
    client_local.post("/capture", {"title": "재시도 큐"}, HTTP_HX_REQUEST="true")
    inbox = get_or_create_inbox(workspace)
    s = Slice.objects.get(area=inbox)
    assert s.title == "재시도 큐" and s.status == "idea" and s.source == "human"

@pytest.mark.django_db
def test_inbox_lists_captures(client_local, workspace):
    inbox = get_or_create_inbox(workspace)
    create_slice(inbox, "정리 대상")
    body = client_local.get("/inbox/").content.decode()
    assert "정리 대상" in body

@pytest.mark.django_db
def test_triage_moves_out_of_inbox(client_local, workspace):
    inbox = get_or_create_inbox(workspace)
    backend = create_area(workspace, "Backend")
    s = create_slice(inbox, "옮길 것")
    client_local.post(f"/slices/{s.id}/triage", {"area_id": backend.id, "status": "planned"}, HTTP_HX_REQUEST="true")
    s.refresh_from_db()
    assert s.area_id == backend.id and s.status == "planned"

@pytest.mark.django_db
def test_area_create_makes_area(client_local, workspace):
    client_local.post("/areas/new", {"name": "Backend"}, HTTP_HX_REQUEST="true")
    assert workspace.areas.filter(is_inbox=False, name="Backend").exists()

@pytest.mark.django_db
def test_capture_returns_oob_inbox_count(client_local, workspace):
    # No full-page reload: capture returns an OOB swap of the sidebar count.
    get_or_create_inbox(workspace)
    resp = client_local.post("/capture", {"title": "빠른 기록"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="inbox-count"' in body
    assert 'hx-swap-oob="true"' in body
    assert ">1<" in body   # count reflects the just-captured slice

@pytest.mark.django_db
def test_area_create_returns_oob_area_nav(client_local, workspace):
    resp = client_local.post("/areas/new", {"name": "새 영역"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="area-nav"' in body
    assert 'hx-swap-oob="true"' in body
    assert "새 영역" in body   # the new area appears in the swapped nav

@pytest.mark.django_db
def test_triage_invalid_status_returns_400(client_local, workspace):
    inbox = get_or_create_inbox(workspace)
    area = create_area(workspace, "Backend")
    s = create_slice(inbox, "잘못된 상태")
    resp = client_local.post(
        f"/slices/{s.id}/triage", {"area_id": area.id, "status": "blocked"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 400
    s.refresh_from_db()
    assert s.area_id == inbox.id and s.status == "idea"

@pytest.mark.django_db
def test_inbox_row_has_no_manual_caret_and_area_placeholder(client_local, workspace):
    from tuckit.core.services.areas import get_or_create_inbox
    from tuckit.core.services.slices import create_slice
    create_slice(get_or_create_inbox(workspace), "미분류 항목")
    body = client_local.get("/inbox/").content.decode()
    assert "</select>▾" not in body          # manual caret removed
    assert "— Area 지정 —" in body           # placeholder present

@pytest.mark.django_db
def test_triage_status_only_keeps_area(client_local, workspace):
    from tuckit.core.services.areas import get_or_create_inbox
    from tuckit.core.services.slices import create_slice
    s = create_slice(get_or_create_inbox(workspace), "상태만 변경")
    resp = client_local.post(f"/slices/{s.id}/triage", {"area_id": "", "status": "planned"})
    assert resp.status_code in (200, 204)
    s.refresh_from_db()
    assert s.area.is_inbox and s.status == "planned"

@pytest.mark.django_db
def test_triage_foreign_area_404s(client_local, workspace):
    inbox = get_or_create_inbox(workspace)
    s = create_slice(inbox, "다른 워크스페이스로")
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other_ws = Workspace.objects.create(org=other_org, name="Other", slug="other")
    foreign_area = create_area(other_ws, "Foreign")
    resp = client_local.post(
        f"/slices/{s.id}/triage", {"area_id": foreign_area.id, "status": "planned"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 404
    s.refresh_from_db()
    assert s.area_id == inbox.id and s.status == "idea"
