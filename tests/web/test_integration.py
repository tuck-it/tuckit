import pytest



@pytest.mark.django_db
def test_all_pages_reachable(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice

    p = f"/{org.slug}"
    a = create_area(org, "Backend")
    s = create_slice(a, "Payment integration", status="building")
    for url in [f"{p}/", f"{p}/triage/", f"{p}/areas/{a.slug}/", f"{p}/areas/{a.slug}/?view=board",
                f"{p}/slices/{s.id}/", f"/{org.slug}/settings/general"]:
        assert client_local.get(url).status_code == 200, url
