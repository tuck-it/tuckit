import pytest
from tuckit.core.services.areas import create_area, get_or_create_triage
from tuckit.core.services.slices import create_slice
from tuckit.core.models import Slice
from tuckit.core.models.org import Org

@pytest.mark.django_db
def test_capture_lands_in_triage_as_idea(client_local, org):
    p = f"/{org.slug}"
    client_local.post(f"{p}/capture", {"title": "Retry queue"}, HTTP_HX_REQUEST="true")
    inbox = get_or_create_triage(org)
    s = Slice.objects.get(area=inbox)
    assert s.title == "Retry queue" and s.status == "idea" and s.source == "human"

@pytest.mark.django_db
def test_triage_lists_captures(client_local, org):
    p = f"/{org.slug}"
    inbox = get_or_create_triage(org)
    create_slice(inbox, "To clean up")
    body = client_local.get(f"{p}/triage/").content.decode()
    assert "To clean up" in body

@pytest.mark.django_db
def test_triage_moves_out(client_local, org):
    inbox = get_or_create_triage(org)
    p = f"/{org.slug}"
    backend = create_area(org, "Backend")
    s = create_slice(inbox, "To move")
    client_local.post(f"{p}/slices/{s.id}/triage", {"area_id": backend.id, "status": "planned"}, HTTP_HX_REQUEST="true")
    s.refresh_from_db()
    assert s.area_id == backend.id and s.status == "planned"

@pytest.mark.django_db
def test_area_create_makes_area(client_local, org):
    p = f"/{org.slug}"
    client_local.post(f"{p}/areas/new", {"name": "Backend"}, HTTP_HX_REQUEST="true")
    assert org.areas.filter(is_triage=False, name="Backend").exists()

@pytest.mark.django_db
def test_capture_returns_toast_count_and_row(client_local, org):
    # No full-page reload: capture returns OOB swaps for toast, count, and the new row.
    p = f"/{org.slug}"
    get_or_create_triage(org)
    resp = client_local.post(f"{p}/capture", {"title": "Quick note"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    body = resp.content.decode()
    # count badge
    assert 'id="triage-count"' in body
    assert ">1<" in body
    # toast
    assert 'id="toast"' in body
    assert "Captured" in body
    # The Triage list is OOB re-rendered (id-matched, reliable) with the new row;
    # it lands only if that page is open. Three elements carry hx-swap-oob="true";
    # #toast, #triage-count, and #triage-list. The form is hx-swap="none", so
    # anything without hx-swap-oob would be silently dropped in the browser.
    assert 'id="triage-list"' in body
    assert body.count('hx-swap-oob="true"') >= 3
    assert "Quick note" in body
    # list is non-empty now, so the "Triage clean" placeholder must be gone
    assert 'id="triage-empty"' not in body

@pytest.mark.django_db
def test_area_create_returns_oob_area_nav(client_local, org):
    p = f"/{org.slug}"
    resp = client_local.post(f"{p}/areas/new", {"name": "New area"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="area-nav"' in body
    assert 'hx-swap-oob="true"' in body
    assert "New area" in body   # the new area appears in the swapped nav

@pytest.mark.django_db
def test_triage_invalid_status_returns_400(client_local, org):
    inbox = get_or_create_triage(org)
    p = f"/{org.slug}"
    area = create_area(org, "Backend")
    s = create_slice(inbox, "Bad status")
    resp = client_local.post(
        f"{p}/slices/{s.id}/triage", {"area_id": area.id, "status": "blocked"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 400
    s.refresh_from_db()
    assert s.area_id == inbox.id and s.status == "idea"

@pytest.mark.django_db
def test_triage_row_has_no_manual_caret_and_area_placeholder(client_local, org):
    from tuckit.core.services.areas import get_or_create_triage
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    create_slice(get_or_create_triage(org), "Uncategorized item")
    body = client_local.get(f"{p}/triage/").content.decode()
    assert "</select>▾" not in body          # manual caret removed
    assert "Assign area" in body           # placeholder present

@pytest.mark.django_db
def test_triage_status_only_keeps_area(client_local, org):
    from tuckit.core.services.areas import get_or_create_triage
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(get_or_create_triage(org), "Status only change")
    resp = client_local.post(f"{p}/slices/{s.id}/triage", {"area_id": "", "status": "planned"})
    assert resp.status_code in (200, 204)
    s.refresh_from_db()
    assert s.area.is_triage and s.status == "planned"

@pytest.mark.django_db
def test_triage_foreign_area_404s(client_local, org):
    p = f"/{org.slug}"
    inbox = get_or_create_triage(org)
    s = create_slice(inbox, "To another workspace")
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    foreign_area = create_area(other_org, "Foreign")
    resp = client_local.post(
        f"{p}/slices/{s.id}/triage", {"area_id": foreign_area.id, "status": "planned"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 404
    s.refresh_from_db()
    assert s.area_id == inbox.id and s.status == "idea"

@pytest.mark.django_db
def test_inbox_heading_and_agent_source_badge(client_local, org):
    from tuckit.core.services.areas import get_or_create_triage
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    tri = get_or_create_triage(org)
    create_slice(tri, "Made by agent", status="idea", source="agent")
    body = client_local.get(f"{p}/triage/").content.decode()
    assert '<h1 class="page-title">Inbox</h1>' in body       # renamed heading
    assert 'class="source-badge is-agent"' in body           # agent item flagged
