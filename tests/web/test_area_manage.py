import pytest

from tuckit.core.models import Area, Org, Workspace
from tuckit.core.services.areas import create_area, get_or_create_triage, list_areas
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_rename_area_updates_and_returns_row(client_local, workspace):
    a = create_area(workspace, "Old")
    resp = client_local.post(f"/areas/{a.id}/rename", {"name": "New"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    a.refresh_from_db()
    assert a.name == "New"
    assert "New" in resp.content.decode()


@pytest.mark.django_db
def test_rename_area_blank_returns_400(client_local, workspace):
    a = create_area(workspace, "Keep")
    resp = client_local.post(f"/areas/{a.id}/rename", {"name": "  "}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    a.refresh_from_db()
    assert a.name == "Keep"


@pytest.mark.django_db
def test_delete_area_returns_204_and_removes(client_local, workspace):
    a = create_area(workspace, "Gone")
    resp = client_local.post(f"/areas/{a.id}/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert not Area.objects.filter(id=a.id).exists()


@pytest.mark.django_db
def test_delete_triage_returns_400(client_local, workspace):
    triage = get_or_create_triage(workspace)
    resp = client_local.post(f"/areas/{triage.id}/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    assert Area.objects.filter(id=triage.id).exists()


@pytest.mark.django_db
def test_manage_foreign_area_404s(client_local, workspace):
    other_org = Org.objects.create(name="Other", slug="other")
    other_ws = Workspace.objects.create(org=other_org, name="Other WS", slug="other-ws")
    foreign = create_area(other_ws, "Foreign")
    resp = client_local.post(f"/areas/{foreign.id}/rename", {"name": "Hax"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 404
    foreign.refresh_from_db()
    assert foreign.name == "Foreign"


@pytest.mark.django_db
def test_reorder_area_before_neighbor(client_local, workspace):
    a = create_area(workspace, "A")
    b = create_area(workspace, "B")
    c = create_area(workspace, "C")
    # move c before a
    resp = client_local.post(
        f"/areas/{c.id}/reorder", {"before_id": a.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 204
    ordered = list(list_areas(workspace))
    # workspace fixture pre-creates Triage + a "Default" area, so filter the
    # full ordered list down to the three areas this test cares about.
    ids = [x.id for x in ordered if x.id in {a.id, b.id, c.id}]
    assert ids == [c.id, a.id, b.id]


@pytest.mark.django_db
def test_reorder_foreign_neighbor_404s(client_local, workspace):
    a = create_area(workspace, "A")
    other_org = Org.objects.create(name="Other", slug="other")
    other_ws = Workspace.objects.create(org=other_org, name="Other WS", slug="other-ws")
    foreign = create_area(other_ws, "Foreign")
    resp = client_local.post(
        f"/areas/{a.id}/reorder", {"before_id": foreign.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_sidebar_row_has_rename_and_delete_affordances(client_local, workspace):
    a = create_area(workspace, "Visible")
    # any authenticated page renders the sidebar
    body = client_local.get("/triage/").content.decode()
    assert f'data-area-id="{a.id}"' in body          # draggable row present
    assert f'/areas/{a.id}/rename' in body           # inline rename form target
    assert f'/areas/{a.id}/delete' in body           # delete button target
    assert "Visible" in body


@pytest.mark.django_db
def test_rename_response_is_swappable_row(client_local, workspace):
    a = create_area(workspace, "Old")
    body = client_local.post(
        f"/areas/{a.id}/rename", {"name": "Fresh"}, HTTP_HX_REQUEST="true"
    ).content.decode()
    assert f'data-area-id="{a.id}"' in body          # returns a full row, not bare text
    assert "Fresh" in body
    assert f'/areas/{a.id}/delete' in body           # actions still wired after rename


@pytest.mark.django_db
def test_sidebar_loads_reorder_script(client_local, workspace):
    create_area(workspace, "Any")
    body = client_local.get("/triage/").content.decode()
    assert "area_nav.js" in body
