import pytest
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_area_view_groups_by_status(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Backend")
    create_slice(a, "Payment integration", status="building")
    create_slice(a, "Login XSS", status="planned")
    resp = client_local.get(f"{p}/areas/{a.slug}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Payment integration" in body and "Login XSS" in body


@pytest.mark.django_db
def test_area_view_other_workspace_404(client_local, org):
    from tuckit.core.models import Org
    from tuckit.core.services.areas import create_area
    p = f"/{org.slug}"
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    a = create_area(other_org, "Secret")
    assert client_local.get(f"{p}/areas/{a.slug}/").status_code == 404


@pytest.mark.django_db
def test_area_header_uses_page_head_and_description(client_local, org):
    a = create_area(org, "Backend")
    p = f"/{org.slug}"
    a.description = "Payments and auth."
    a.save()
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert 'class="page-head"' in body
    assert 'class="page-title"' in body
    assert 'class="area-desc"' in body
    assert "Payments and auth." in body


@pytest.mark.django_db
def test_area_header_omits_description_when_blank(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Backend")  # description defaults to ""
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert 'class="page-head"' in body
    assert 'class="area-desc"' not in body


@pytest.mark.django_db
def test_area_list_collapses_shipped_and_dropped(client_local, org):
    a = create_area(org, "Backend")
    create_slice(a, "building one", status="building")
    create_slice(a, "shipped one", status="shipped")
    create_slice(a, "dropped one", status="dropped")
    p = f"/{org.slug}"
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
    p = f"/{org.slug}"
    a = create_area(org, "Empty")
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert "No slices yet." in body
    assert "There are no slices yet" not in body


@pytest.mark.django_db
def test_add_slice_creates_idea_slice_in_area(client_local, org):
    from tuckit.core.models import Slice
    p = f"/{org.slug}"
    a = create_area(org, "Backend")
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
    p = f"/{org.slug}"
    a = create_area(org, "Backend")
    resp = client_local.post(f"{p}/areas/{a.slug}/slices", {"title": "   "},
                             HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert Slice.objects.filter(area=a).count() == 0
    assert 'id="area-list"' in resp.content.decode()


@pytest.mark.django_db
def test_area_page_autoopens_slice_add_on_focus_hint(client_local, org):
    area = create_area(org, "Backend")
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/areas/{area.slug}/?focus=slice").content.decode()
    assert "ob-focus-slice" in body


@pytest.mark.django_db
def test_add_slice_other_workspace_404(client_local, org):
    from tuckit.core.models import Org
    p = f"/{org.slug}"
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    a = create_area(other_org, "Secret")
    resp = client_local.post(f"{p}/areas/{a.slug}/slices", {"title": "x"},
                             HTTP_HX_REQUEST="true")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_area_quick_add_accepts_rich_fields(client_local, org):
    from tuckit.core.models import Slice
    a = create_area(org, "Backend")
    client_local.post(
        f"/{org.slug}/areas/{a.slug}/slices",
        {"title": "Retry webhooks", "status": "planned", "spec": "exp backoff", "tags": ["infra"]},
        HTTP_HX_REQUEST="true",
    )
    s = Slice.objects.get(title="Retry webhooks")
    assert s.area_id == a.id
    assert s.status == "planned"
    assert s.spec == "exp backoff"
    assert {t.name for t in s.tags.all()} == {"infra"}


@pytest.mark.django_db
def test_area_quick_add_title_only_still_works(client_local, org):
    from tuckit.core.models import Slice
    a = create_area(org, "Backend")
    client_local.post(f"/{org.slug}/areas/{a.slug}/slices", {"title": "just this"}, HTTP_HX_REQUEST="true")
    s = Slice.objects.get(title="just this")
    assert s.area_id == a.id and s.status == "idea"


@pytest.mark.django_db
def test_area_quick_add_honors_chosen_area(client_local, org):
    from tuckit.core.models import Slice
    a = create_area(org, "Backend")
    b = create_area(org, "Frontend")
    client_local.post(
        f"/{org.slug}/areas/{a.slug}/slices",
        {"title": "moved one", "area_id": b.id},
        HTTP_HX_REQUEST="true",
    )
    assert Slice.objects.get(title="moved one").area_id == b.id


@pytest.mark.django_db
def test_area_page_has_new_slice_modal(client_local, org):
    a = create_area(org, "Backend")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/").content.decode()
    assert "＋ New slice" in body                     # the modal trigger button
    assert f"/areas/{a.slug}/slices" in body          # modal posts a full slice to this area
    assert "New slice in Backend" in body             # modal is a distinct, titled surface


@pytest.mark.django_db
def test_focus_slice_opens_modal(client_local, org):
    # Onboarding Step 2 deep-links ?focus=slice — the create modal auto-opens.
    a = create_area(org, "Empty")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/?focus=slice").content.decode()
    assert "open: true" in body


@pytest.mark.django_db
def test_area_page_modal_closed_by_default(client_local, org):
    a = create_area(org, "Backend")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/").content.decode()
    assert "open: false" in body
