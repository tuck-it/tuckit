import pytest


@pytest.mark.django_db
def test_all_pages_reachable(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice

    a = create_area(workspace, "Backend")
    s = create_slice(a, "결제 도입", status="building")
    for url in ["/", "/inbox/", f"/areas/{a.slug}/", f"/areas/{a.slug}/?view=board",
                f"/slices/{s.id}/", "/settings/"]:
        assert client_local.get(url).status_code == 200, url
