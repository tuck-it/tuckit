import pytest
from tuckit.core.services.areas import create_area, get_or_create_triage
from tuckit.core.services.slices import create_slice
from tuckit.core.models import Slice
from tuckit.core.models.org import Org
from tuckit.core.models.workspace import Workspace

@pytest.mark.django_db
def test_capture_lands_in_triage_as_idea(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    client_local.post(f"{p}/capture", {"title": "재시도 큐"}, HTTP_HX_REQUEST="true")
    inbox = get_or_create_triage(workspace)
    s = Slice.objects.get(area=inbox)
    assert s.title == "재시도 큐" and s.status == "idea" and s.source == "human"

@pytest.mark.django_db
def test_triage_lists_captures(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    inbox = get_or_create_triage(workspace)
    create_slice(inbox, "정리 대상")
    body = client_local.get(f"{p}/triage/").content.decode()
    assert "정리 대상" in body

@pytest.mark.django_db
def test_triage_moves_out(client_local, workspace):
    inbox = get_or_create_triage(workspace)
    p = f"/{workspace.org.slug}/{workspace.slug}"
    backend = create_area(workspace, "Backend")
    s = create_slice(inbox, "옮길 것")
    client_local.post(f"{p}/slices/{s.id}/triage", {"area_id": backend.id, "status": "planned"}, HTTP_HX_REQUEST="true")
    s.refresh_from_db()
    assert s.area_id == backend.id and s.status == "planned"

@pytest.mark.django_db
def test_area_create_makes_area(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    client_local.post(f"{p}/areas/new", {"name": "Backend"}, HTTP_HX_REQUEST="true")
    assert workspace.areas.filter(is_triage=False, name="Backend").exists()

@pytest.mark.django_db
def test_capture_returns_toast_count_and_row(client_local, workspace):
    # No full-page reload: capture returns OOB swaps for toast, count, and the new row.
    p = f"/{workspace.org.slug}/{workspace.slug}"
    get_or_create_triage(workspace)
    resp = client_local.post(f"{p}/capture", {"title": "빠른 기록"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    body = resp.content.decode()
    # count badge
    assert 'id="triage-count"' in body
    assert ">1<" in body
    # toast
    assert 'id="toast"' in body
    assert "Captured" in body
    # The Triage list is OOB re-rendered (id-matched, reliable) with the new row;
    # it lands only if that page is open. Three elements carry hx-swap-oob="true":
    # #toast, #triage-count, and #triage-list. The form is hx-swap="none", so
    # anything without hx-swap-oob would be silently dropped in the browser.
    assert 'id="triage-list"' in body
    assert body.count('hx-swap-oob="true"') >= 3
    assert "빠른 기록" in body
    # list is non-empty now, so the "Triage clean" placeholder must be gone
    assert 'id="triage-empty"' not in body

@pytest.mark.django_db
def test_area_create_returns_oob_area_nav(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    resp = client_local.post(f"{p}/areas/new", {"name": "새 영역"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="area-nav"' in body
    assert 'hx-swap-oob="true"' in body
    assert "새 영역" in body   # the new area appears in the swapped nav

@pytest.mark.django_db
def test_triage_invalid_status_returns_400(client_local, workspace):
    inbox = get_or_create_triage(workspace)
    p = f"/{workspace.org.slug}/{workspace.slug}"
    area = create_area(workspace, "Backend")
    s = create_slice(inbox, "잘못된 상태")
    resp = client_local.post(
        f"{p}/slices/{s.id}/triage", {"area_id": area.id, "status": "blocked"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 400
    s.refresh_from_db()
    assert s.area_id == inbox.id and s.status == "idea"

@pytest.mark.django_db
def test_triage_row_has_no_manual_caret_and_area_placeholder(client_local, workspace):
    from tuckit.core.services.areas import get_or_create_triage
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    create_slice(get_or_create_triage(workspace), "미분류 항목")
    body = client_local.get(f"{p}/triage/").content.decode()
    assert "</select>▾" not in body          # manual caret removed
    assert "Assign area" in body           # placeholder present

@pytest.mark.django_db
def test_triage_status_only_keeps_area(client_local, workspace):
    from tuckit.core.services.areas import get_or_create_triage
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(get_or_create_triage(workspace), "상태만 변경")
    resp = client_local.post(f"{p}/slices/{s.id}/triage", {"area_id": "", "status": "planned"})
    assert resp.status_code in (200, 204)
    s.refresh_from_db()
    assert s.area.is_triage and s.status == "planned"

@pytest.mark.django_db
def test_triage_foreign_area_404s(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    inbox = get_or_create_triage(workspace)
    s = create_slice(inbox, "다른 워크스페이스로")
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other_ws = Workspace.objects.create(org=other_org, name="Other", slug="other")
    foreign_area = create_area(other_ws, "Foreign")
    resp = client_local.post(
        f"{p}/slices/{s.id}/triage", {"area_id": foreign_area.id, "status": "planned"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 404
    s.refresh_from_db()
    assert s.area_id == inbox.id and s.status == "idea"

@pytest.mark.django_db
def test_inbox_heading_and_agent_source_badge(client_local, workspace):
    from tuckit.core.services.areas import get_or_create_triage
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    tri = get_or_create_triage(workspace)
    create_slice(tri, "에이전트가 만든 것", status="idea", source="agent")
    body = client_local.get(f"{p}/triage/").content.decode()
    assert '<h1 class="page-title">Inbox</h1>' in body       # renamed heading
    assert 'class="source-badge is-agent"' in body           # agent item flagged
