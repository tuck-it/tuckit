import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


def _p(org):
    return f"/{org.slug}"


@pytest.mark.django_db
def test_areas_page_empty_state(client_local, org):
    body = client_local.get(f"{_p(org)}/areas/").content.decode()
    assert "domain of responsibility" in body  # the Area definition copy
    assert "/areas/new" in body                 # real Create Area CTA
    assert 'class="areas-empty"' in body


@pytest.mark.django_db
def test_areas_page_lists_areas(client_local, org):
    area = create_area(org, "Backend")
    create_slice(area, "Retry webhooks", status="open")
    body = client_local.get(f"{_p(org)}/areas/").content.decode()
    assert "Backend" in body
    assert 'class="areas-empty"' not in body
    assert f"/areas/{area.slug}/" in body       # card links into the area


@pytest.mark.django_db
def test_areas_page_slice_count_excludes_dropped(client_local, org):
    area = create_area(org, "Backend")
    create_slice(area, "Retry webhooks", status="open")
    create_slice(area, "Add metrics", status="open")
    create_slice(area, "Old approach", status="dropped")
    body = client_local.get(f"{_p(org)}/areas/").content.decode()
    assert "2 slice" in body
    assert "3 slice" not in body


@pytest.mark.django_db
def test_areas_route_resolves(client_local, org):
    from django.urls import reverse
    url = reverse("web:areas", kwargs={"org_slug": org.slug})
    assert client_local.get(url).status_code == 200
