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
def test_area_board_omits_dropped_and_links_to_it(client_local, org):
    a = create_area(org, "Backend")
    create_slice(a, "building one", status="building")
    create_slice(a, "dropped one", status="dropped")
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert 'id="board"' in body
    assert "building one" in body
    assert "dropped one" not in body            # no dropped column on the board
    assert "Dropped (1)" in body                # ...but a route to it
    assert 'href="?status=dropped"' in body


@pytest.mark.django_db
def test_area_board_hides_dropped_link_when_none(client_local, org):
    a = create_area(org, "Backend")
    create_slice(a, "building one", status="building")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/").content.decode()
    assert "Dropped (" not in body


@pytest.mark.django_db
def test_area_status_filter_lists_dropped_flat(client_local, org):
    a = create_area(org, "Backend")
    create_slice(a, "dropped one", status="dropped")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/?status=dropped").content.decode()
    assert "dropped one" in body
    assert 'id="board"' not in body
    assert "← Board" in body
    assert f'href="/{org.slug}/areas/{a.slug}/"' in body


@pytest.mark.django_db
def test_area_caps_shipped_and_links_to_all(client_local, org):
    org.shipped_board_mode = "count"
    org.shipped_board_limit = 1
    org.save(update_fields=["shipped_board_mode", "shipped_board_limit", "updated_at"])
    a = create_area(org, "Backend")
    create_slice(a, "shipped one", status="shipped")
    create_slice(a, "shipped two", status="shipped")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/").content.decode()
    # Shipped is off-board: header link shows the total, no shipped column.
    assert "Shipped (2)" in body
    assert 'href="?status=shipped"' in body
    assert 'data-stage="shipped"' not in body
    # ...and the uncapped surface behind that link shows both
    all_body = client_local.get(f"/{org.slug}/areas/{a.slug}/?status=shipped").content.decode()
    assert "shipped one" in all_body and "shipped two" in all_body


@pytest.mark.django_db
def test_area_ignores_stale_view_param(client_local, org):
    """?view= is gone. An old bookmark must land on the board, not 404."""
    a = create_area(org, "Backend")
    resp = client_local.get(f"/{org.slug}/areas/{a.slug}/?view=list")
    assert resp.status_code == 200
    assert 'id="board"' in resp.content.decode()


@pytest.mark.django_db
def test_area_has_no_view_toggle(client_local, org):
    a = create_area(org, "Backend")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/").content.decode()
    assert 'href="?view=list"' not in body
    assert 'href="?view=board"' not in body


@pytest.mark.django_db
def test_new_slice_button_lives_in_the_page_head(client_local, org):
    a = create_area(org, "Backend")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/").content.decode()
    head = body[body.index('class="page-head"'):body.index('id="board"')]
    assert "page-head-r" in head
    assert "＋ New slice" in head


@pytest.mark.django_db
def test_area_empty_copy_is_english(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Empty")
    body = client_local.get(f"{p}/areas/{a.slug}/").content.decode()
    assert "No slices yet." in body


@pytest.mark.django_db
def test_add_slice_creates_planned_slice_in_area(client_local, org):
    from tuckit.core.models import Slice
    p = f"/{org.slug}"
    a = create_area(org, "Backend")
    resp = client_local.post(f"{p}/areas/{a.slug}/slices", {"title": "new idea"},
                             HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    s = Slice.objects.get(area=a, title="new idea")
    assert s.status == "planned"
    body = resp.content.decode()
    assert 'id="board"' in body
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
    assert 'id="board"' in resp.content.decode()


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
    assert s.area_id == a.id and s.status == "planned"


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
    assert "Create a new Slice" in body               # modal is a distinct, titled surface
    assert "in <strong>Backend</strong>" in body      # ...and it names the target area


@pytest.mark.django_db
def test_focus_slice_opens_modal(client_local, org):
    # Onboarding Step 2 deep-links ?focus=slice — the create modal auto-opens.
    a = create_area(org, "Empty")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/?focus=slice").content.decode()
    assert "modal: true" in body


@pytest.mark.django_db
def test_area_page_modal_closed_by_default(client_local, org):
    a = create_area(org, "Backend")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/").content.decode()
    assert "open: false" in body
