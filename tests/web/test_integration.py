import pytest


@pytest.mark.django_db
def test_all_pages_reachable(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice

    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Backend")
    s = create_slice(a, "결제 도입", status="building")
    for url in [f"{p}/", f"{p}/triage/", f"{p}/areas/{a.slug}/", f"{p}/areas/{a.slug}/?view=board",
                f"{p}/slices/{s.id}/", f"/{workspace.org.slug}/settings/workspaces/{workspace.slug}/general"]:
        assert client_local.get(url).status_code == 200, url
