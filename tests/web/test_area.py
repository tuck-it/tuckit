import pytest
from tuckit.core.models import Workspace
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_area_view_groups_by_status(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Backend")
    create_slice(a, "결제 도입", status="building")
    create_slice(a, "로그인 XSS", status="planned")
    resp = client_local.get(f"{p}/areas/{a.slug}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "결제 도입" in body and "로그인 XSS" in body


@pytest.mark.django_db
def test_area_view_other_workspace_404(client_local, org):
    from tuckit.core.models import Org, Workspace
    from tuckit.core.services.areas import create_area
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other = Workspace.objects.create(org=other_org, name="O", slug="o")
    a = create_area(other.org, "Secret")
    assert client_local.get(f"{p}/areas/{a.slug}/").status_code == 404


@pytest.mark.django_db
def test_area_header_uses_page_head_and_description(client_local, org):
    ws = Workspace.objects.get(org=org)
    a = create_area(ws.org, "Backend")
    p = f"/{org.slug}/{ws.slug}"
    a.description = "Payments and auth."
    a.save()
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert 'class="page-head"' in body
    assert 'class="page-title"' in body
    assert 'class="area-desc"' in body
    assert "Payments and auth." in body


@pytest.mark.django_db
def test_area_header_omits_description_when_blank(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Backend")  # description defaults to ""
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert 'class="page-head"' in body
    assert 'class="area-desc"' not in body


@pytest.mark.django_db
def test_area_list_collapses_shipped_and_dropped(client_local, org):
    ws = Workspace.objects.get(org=org)
    a = create_area(ws.org, "Backend")
    create_slice(a, "building one", status="building")
    create_slice(a, "shipped one", status="shipped")
    create_slice(a, "dropped one", status="dropped")
    p = f"/{org.slug}/{ws.slug}"
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert 'id="area-list"' in body
    # shipped + dropped are inside <details>; building is not
    shipped_pos = body.index("shipped one")
    dropped_pos = body.index("dropped one")
    details_open = [m for m in range(len(body)) if body.startswith("<details", m)]
    # both shipped and dropped titles follow a <details> that opens before them
    assert any(d < shipped_pos for d in details_open)
    assert any(d < dropped_pos for d in details_open)
    # building renders unwrapped (before the first <details>, which is shipped)
    assert body.index("building one") < body.index("<details")


@pytest.mark.django_db
def test_area_list_empty_copy_is_english(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Empty")
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert "No slices yet." in body
    assert "아직 Slice가 없어요" not in body


@pytest.mark.django_db
def test_add_slice_creates_idea_slice_in_area(client_local, org):
    from tuckit.core.models import Slice
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Backend")
    resp = client_local.post(f"{p}/areas/{a.slug}/slices", {"title": "new idea"},
                             HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    s = Slice.objects.get(area=a, title="new idea")
    assert s.status == "idea"
    body = resp.content.decode()
    assert 'id="area-list"' in body
    assert "new idea" in body


@pytest.mark.django_db
def test_add_slice_ignores_blank_title(client_local, org):
    from tuckit.core.models import Slice
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Backend")
    resp = client_local.post(f"{p}/areas/{a.slug}/slices", {"title": "   "},
                             HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert Slice.objects.filter(area=a).count() == 0
    assert 'id="area-list"' in resp.content.decode()


@pytest.mark.django_db
def test_area_page_autoopens_slice_add_on_focus_hint(client_local, org):
    ws = Workspace.objects.get(org=org)
    area = create_area(ws.org, "Backend")
    p = f"/{org.slug}/{ws.slug}"
    body = client_local.get(f"{p}/areas/{area.slug}/?focus=slice").content.decode()
    assert "ob-focus-slice" in body


@pytest.mark.django_db
def test_add_slice_other_workspace_404(client_local, org):
    from tuckit.core.models import Org, Workspace
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other = Workspace.objects.create(org=other_org, name="O", slug="o")
    a = create_area(other.org, "Secret")
    resp = client_local.post(f"{p}/areas/{a.slug}/slices", {"title": "x"},
                             HTTP_HX_REQUEST="true")
    assert resp.status_code == 404
