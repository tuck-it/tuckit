import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_lens_routes_are_gone(client_local, org):
    """Both pages were orphans — the only link to either was a Home column that
    the band redesign removes. your turn / in progress replace them."""
    from django.urls import NoReverseMatch, reverse

    assert client_local.get(f"/{org.slug}/attention/").status_code == 404
    assert client_local.get(f"/{org.slug}/in-progress/").status_code == 404

    for name in ("web:attention", "web:in_progress"):
        with pytest.raises(NoReverseMatch):
            reverse(name, args=[org.slug])


@pytest.mark.django_db
def test_roadmap_page_shows_distribution_and_slices(client_local, org):
    a = create_area(org, "Backend")
    create_slice(a, "Roadmap item", status="planned")
    create_slice(a, "Dropped item", status="dropped")  # dropped never bucketed
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Roadmap item" in body
    assert 'data-status="planned"' in body   # rendered in its status column
    assert "Dropped item" not in body   # dropped slices excluded from the board


@pytest.mark.django_db
def test_board_page_heading(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert '<h1 class="page-title">Board</h1>' in body
