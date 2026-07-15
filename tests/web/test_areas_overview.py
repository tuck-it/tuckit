import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


def _p(ws):
    return f"/{ws.org.slug}/{ws.slug}"


@pytest.mark.django_db
def test_areas_page_empty_state(client_local, workspace):
    body = client_local.get(f"{_p(workspace)}/areas/").content.decode()
    assert "domain of responsibility" in body  # the Area definition copy
    assert "/areas/new" in body                 # real Create Area CTA
    assert 'class="areas-empty"' in body


@pytest.mark.django_db
def test_areas_page_lists_areas(client_local, workspace):
    area = create_area(workspace, "Backend")
    create_slice(area, "Retry webhooks", status="idea")
    body = client_local.get(f"{_p(workspace)}/areas/").content.decode()
    assert "Backend" in body
    assert 'class="areas-empty"' not in body
    assert f"/areas/{area.slug}/" in body       # card links into the area


@pytest.mark.django_db
def test_areas_page_slice_count_excludes_dropped(client_local, workspace):
    area = create_area(workspace, "Backend")
    create_slice(area, "Retry webhooks", status="idea")
    create_slice(area, "Add metrics", status="planned")
    create_slice(area, "Old approach", status="dropped")
    body = client_local.get(f"{_p(workspace)}/areas/").content.decode()
    assert "2 slice" in body
    assert "3 slice" not in body


@pytest.mark.django_db
def test_areas_route_resolves(client_local, workspace):
    from django.urls import reverse
    url = reverse("web:areas", kwargs={"org_slug": workspace.org.slug, "ws_slug": workspace.slug})
    assert client_local.get(url).status_code == 200
