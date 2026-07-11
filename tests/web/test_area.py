import pytest
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_area_view_groups_by_status(client_local, workspace):
    a = create_area(workspace, "Backend")
    create_slice(a, "결제 도입", status="building")
    create_slice(a, "로그인 XSS", status="planned")
    resp = client_local.get(f"/areas/{a.slug}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "결제 도입" in body and "로그인 XSS" in body


@pytest.mark.django_db
def test_area_view_other_workspace_404(client_local):
    from tuckit.core.models import Org, Workspace
    from tuckit.core.services.areas import create_area
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other = Workspace.objects.create(org=other_org, name="O", slug="o")
    a = create_area(other, "Secret")
    assert client_local.get(f"/areas/{a.slug}/").status_code == 404
