import pytest

from tuckit.core.models import Area, Org
from tuckit.core.services.areas import create_area, get_or_create_triage, list_areas


@pytest.mark.django_db
def test_rename_area_updates_and_returns_row(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Old")
    resp = client_local.post(f"{p}/areas/{a.id}/rename", {"name": "New"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    a.refresh_from_db()
    assert a.name == "New"
    assert "New" in resp.content.decode()


@pytest.mark.django_db
def test_rename_area_blank_returns_400(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Keep")
    resp = client_local.post(f"{p}/areas/{a.id}/rename", {"name": "  "}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    a.refresh_from_db()
    assert a.name == "Keep"


@pytest.mark.django_db
def test_delete_area_returns_204_and_removes(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Gone")
    resp = client_local.post(f"{p}/areas/{a.id}/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert not Area.objects.filter(id=a.id).exists()


@pytest.mark.django_db
def test_delete_triage_returns_400(client_local, org):
    p = f"/{org.slug}"
    triage = get_or_create_triage(org)
    resp = client_local.post(f"{p}/areas/{triage.id}/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    assert Area.objects.filter(id=triage.id).exists()


@pytest.mark.django_db
def test_manage_foreign_area_404s(client_local, org):
    other_org = Org.objects.create(name="Other", slug="other")
    p = f"/{org.slug}"
    foreign = create_area(other_org, "Foreign")
    resp = client_local.post(f"{p}/areas/{foreign.id}/rename", {"name": "Hax"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 404
    foreign.refresh_from_db()
    assert foreign.name == "Foreign"


@pytest.mark.django_db
def test_reorder_area_before_neighbor(client_local, org):
    a = create_area(org, "A")
    b = create_area(org, "B")
    c = create_area(org, "C")
    p = f"/{org.slug}"
    # move c before a
    resp = client_local.post(
        f"{p}/areas/{c.id}/reorder", {"before_id": a.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 204
    ordered = list(list_areas(org))
    # the org fixture pre-creates only Triage, so filter the full ordered
    # list down to the three areas this test cares about.
    ids = [x.id for x in ordered if x.id in {a.id, b.id, c.id}]
    assert ids == [c.id, a.id, b.id]


@pytest.mark.django_db
def test_reorder_foreign_neighbor_404s(client_local, org):
    a = create_area(org, "A")
    other_org = Org.objects.create(name="Other", slug="other")
    p = f"/{org.slug}"
    foreign = create_area(other_org, "Foreign")
    resp = client_local.post(
        f"{p}/areas/{a.id}/reorder", {"before_id": foreign.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_sidebar_row_has_rename_and_delete_affordances(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Visible")
    # any authenticated page renders the sidebar
    body = client_local.get(f"{p}/triage/").content.decode()
    assert f'data-area-id="{a.id}"' in body          # draggable row present
    assert f'{p}/areas/{a.id}/rename' in body         # inline rename form target
    assert f'{p}/areas/{a.id}/delete' in body         # delete button target
    assert "Visible" in body


@pytest.mark.django_db
def test_rename_response_is_swappable_row(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Old")
    body = client_local.post(
        f"{p}/areas/{a.id}/rename", {"name": "Fresh"}, HTTP_HX_REQUEST="true"
    ).content.decode()
    assert f'data-area-id="{a.id}"' in body          # returns a full row, not bare text
    assert "Fresh" in body
    assert f'{p}/areas/{a.id}/delete' in body         # actions still wired after rename


@pytest.mark.django_db
def test_sidebar_loads_reorder_script(client_local, org):
    p = f"/{org.slug}"
    create_area(org, "Any")
    body = client_local.get(f"{p}/triage/").content.decode()
    assert "area_nav.js" in body


@pytest.mark.django_db
def test_rename_current_area_keeps_active_highlight(client_local, org):
    # Renaming the area you are currently viewing must not drop its sidebar
    # highlight. htmx sends HX-Current-URL; the view uses it to re-mark active.
    p = f"/{org.slug}"
    a = create_area(org, "Cur")
    body = client_local.post(
        f"{p}/areas/{a.id}/rename", {"name": "Cur2"},
        HTTP_HX_REQUEST="true",
        HTTP_HX_CURRENT_URL=f"http://testserver{p}/areas/{a.slug}/",
    ).content.decode()
    assert "nav--active" in body


@pytest.mark.django_db
def test_rename_other_area_is_not_active(client_local, org):
    # Renaming an area while viewing a different page leaves it un-highlighted.
    p = f"/{org.slug}"
    a = create_area(org, "Other")
    body = client_local.post(
        f"{p}/areas/{a.id}/rename", {"name": "Other2"},
        HTTP_HX_REQUEST="true",
        HTTP_HX_CURRENT_URL=f"http://testserver{p}/triage/",
    ).content.decode()
    assert "nav--active" not in body


@pytest.mark.django_db
def test_area_edit_updates_name_and_description(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Old", description="old desc")
    resp = client_local.post(
        f"{p}/areas/{a.id}/edit", {"name": "New", "description": "new desc"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 200
    a.refresh_from_db()
    assert a.name == "New"
    assert a.description == "new desc"
    assert "New" in resp.content.decode()


@pytest.mark.django_db
def test_area_edit_blank_name_returns_400(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Keep", description="d")
    resp = client_local.post(f"{p}/areas/{a.id}/edit", {"name": "  ", "description": "x"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    a.refresh_from_db()
    assert a.name == "Keep"


@pytest.mark.django_db
def test_area_edit_foreign_area_404s(client_local, org):
    other = Org.objects.create(name="Other", slug="other")
    foreign = create_area(other, "Foreign")
    resp = client_local.post(
        f"/{org.slug}/areas/{foreign.id}/edit", {"name": "Hax"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_area_page_exposes_edit_form(client_local, org):
    a = create_area(org, "Backend")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/").content.decode()
    assert f"/areas/{a.id}/edit" in body      # edit form target present
    assert 'name="description"' in body        # description field in the modal


@pytest.mark.django_db
def test_sidebar_create_form_not_prefilled_on_area_page(client_local, org):
    # The sidebar "+ Area" create form is global; on an area detail page it must
    # NOT inherit that page's `area` (name/description) — else new-area creation
    # starts pre-filled with the current area's values.
    import re
    a = create_area(org, "Backend", description="APIs and jobs")
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/").content.decode()
    m = re.search(r'<form class="area-add".*?</form>', body, re.S)
    assert m is not None
    form = m.group(0)
    assert 'value="Backend"' not in form      # name not prefilled
    assert "APIs and jobs" not in form         # description not prefilled
