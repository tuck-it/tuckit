import pytest
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.models import Org, Slice, Workspace


@pytest.mark.django_db
def test_board_view_renders_columns(client_local, workspace):
    a = create_area(workspace, "B")
    create_slice(a, "결제", status="building")
    resp = client_local.get(f"/areas/{a.slug}/?view=board")
    body = resp.content.decode()
    assert "결제" in body
    assert 'data-status="building"' in body

@pytest.mark.django_db
def test_board_column_head_has_dot_and_count(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(workspace, "제품")
    create_slice(a, "카드 A", status="building")
    body = client_local.get(f"/areas/{a.slug}/?view=board").content.decode()
    assert "board-col-head" in body
    assert "status-dot--building" in body

@pytest.mark.django_db
def test_move_changes_status(client_local, workspace):
    a = create_area(workspace, "B")
    s = create_slice(a, "결제", status="planned")
    resp = client_local.post(f"/slices/{s.id}/move", {"status": "building"}, HTTP_HX_REQUEST="true")
    assert resp.status_code in (200, 204)
    assert Slice.objects.get(pk=s.id).status == "building"

@pytest.mark.django_db
def test_move_reorders_within_column(client_local, workspace):
    a = create_area(workspace, "B")
    s1 = create_slice(a, "one", status="planned")
    s2 = create_slice(a, "two", status="planned")
    # move s2 before s1
    client_local.post(f"/slices/{s2.id}/move", {"status": "planned", "before_id": s1.id}, HTTP_HX_REQUEST="true")
    ordered = list(Slice.objects.filter(area=a, status="planned").order_by("rank"))
    assert [x.id for x in ordered] == [s2.id, s1.id]

@pytest.mark.django_db
def test_move_invalid_status_returns_400_and_unchanged(client_local, workspace):
    a = create_area(workspace, "B")
    s = create_slice(a, "결제", status="planned")
    resp = client_local.post(f"/slices/{s.id}/move", {"status": "blocked"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    assert Slice.objects.get(pk=s.id).status == "planned"

@pytest.mark.django_db
def test_move_foreign_neighbor_404s_without_change(client_local, workspace):
    a = create_area(workspace, "B")
    s = create_slice(a, "결제", status="planned")
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other_ws = Workspace.objects.create(org=other_org, name="Other", slug="other")
    other_area = create_area(other_ws, "Other Area")
    n = create_slice(other_area, "foreign", status="planned")
    resp = client_local.post(
        f"/slices/{s.id}/move",
        {"status": "building", "before_id": n.id},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 404
    assert Slice.objects.get(pk=s.id).status == "planned"
