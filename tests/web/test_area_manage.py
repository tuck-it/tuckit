import pytest

from tuckit.core.models import Area, Org, Workspace
from tuckit.core.services.areas import create_area, get_or_create_triage, list_areas


@pytest.mark.django_db
def test_rename_area_updates_and_returns_row(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Old")
    resp = client_local.post(f"{p}/areas/{a.id}/rename", {"name": "New"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    a.refresh_from_db()
    assert a.name == "New"
    assert "New" in resp.content.decode()


@pytest.mark.django_db
def test_rename_area_blank_returns_400(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Keep")
    resp = client_local.post(f"{p}/areas/{a.id}/rename", {"name": "  "}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    a.refresh_from_db()
    assert a.name == "Keep"


@pytest.mark.django_db
def test_delete_area_returns_204_and_removes(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Gone")
    resp = client_local.post(f"{p}/areas/{a.id}/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert not Area.objects.filter(id=a.id).exists()


@pytest.mark.django_db
def test_delete_triage_returns_400(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    triage = get_or_create_triage(ws.org)
    resp = client_local.post(f"{p}/areas/{triage.id}/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    assert Area.objects.filter(id=triage.id).exists()


@pytest.mark.django_db
def test_manage_foreign_area_404s(client_local, org):
    ws = Workspace.objects.get(org=org)
    other_org = Org.objects.create(name="Other", slug="other")
    other_ws = Workspace.objects.create(org=other_org, name="Other WS", slug="other-ws")
    p = f"/{org.slug}/{ws.slug}"
    foreign = create_area(other_ws.org, "Foreign")
    resp = client_local.post(f"{p}/areas/{foreign.id}/rename", {"name": "Hax"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 404
    foreign.refresh_from_db()
    assert foreign.name == "Foreign"


@pytest.mark.django_db
def test_reorder_area_before_neighbor(client_local, org):
    ws = Workspace.objects.get(org=org)
    a = create_area(ws.org, "A")
    b = create_area(ws.org, "B")
    c = create_area(ws.org, "C")
    p = f"/{org.slug}/{ws.slug}"
    # move c before a
    resp = client_local.post(
        f"{p}/areas/{c.id}/reorder", {"before_id": a.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 204
    ordered = list(list_areas(ws.org))
    # the workspace fixture pre-creates only Triage, so filter the full ordered
    # list down to the three areas this test cares about.
    ids = [x.id for x in ordered if x.id in {a.id, b.id, c.id}]
    assert ids == [c.id, a.id, b.id]


@pytest.mark.django_db
def test_reorder_foreign_neighbor_404s(client_local, org):
    ws = Workspace.objects.get(org=org)
    a = create_area(ws.org, "A")
    other_org = Org.objects.create(name="Other", slug="other")
    other_ws = Workspace.objects.create(org=other_org, name="Other WS", slug="other-ws")
    p = f"/{org.slug}/{ws.slug}"
    foreign = create_area(other_ws.org, "Foreign")
    resp = client_local.post(
        f"{p}/areas/{a.id}/reorder", {"before_id": foreign.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_sidebar_row_has_rename_and_delete_affordances(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Visible")
    # any authenticated page renders the sidebar
    body = client_local.get(f"{p}/triage/").content.decode()
    assert f'data-area-id="{a.id}"' in body          # draggable row present
    assert f'{p}/areas/{a.id}/rename' in body         # inline rename form target
    assert f'{p}/areas/{a.id}/delete' in body         # delete button target
    assert "Visible" in body


@pytest.mark.django_db
def test_rename_response_is_swappable_row(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Old")
    body = client_local.post(
        f"{p}/areas/{a.id}/rename", {"name": "Fresh"}, HTTP_HX_REQUEST="true"
    ).content.decode()
    assert f'data-area-id="{a.id}"' in body          # returns a full row, not bare text
    assert "Fresh" in body
    assert f'{p}/areas/{a.id}/delete' in body         # actions still wired after rename


@pytest.mark.django_db
def test_sidebar_loads_reorder_script(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    create_area(ws.org, "Any")
    body = client_local.get(f"{p}/triage/").content.decode()
    assert "area_nav.js" in body


@pytest.mark.django_db
def test_rename_current_area_keeps_active_highlight(client_local, org):
    # Renaming the area you are currently viewing must not drop its sidebar
    # highlight. htmx sends HX-Current-URL; the view uses it to re-mark active.
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Cur")
    body = client_local.post(
        f"{p}/areas/{a.id}/rename", {"name": "Cur2"},
        HTTP_HX_REQUEST="true",
        HTTP_HX_CURRENT_URL=f"http://testserver{p}/areas/{a.slug}/",
    ).content.decode()
    assert "nav--active" in body


@pytest.mark.django_db
def test_rename_other_area_is_not_active(client_local, org):
    # Renaming an area while viewing a different page leaves it un-highlighted.
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    a = create_area(ws.org, "Other")
    body = client_local.post(
        f"{p}/areas/{a.id}/rename", {"name": "Other2"},
        HTTP_HX_REQUEST="true",
        HTTP_HX_CURRENT_URL=f"http://testserver{p}/triage/",
    ).content.decode()
    assert "nav--active" not in body
