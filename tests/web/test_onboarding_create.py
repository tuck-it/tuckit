import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


def _p(ws):
    return f"/{ws.org.slug}/{ws.slug}"


@pytest.mark.django_db
def test_area_create_oob_refreshes_widget(client_local, workspace):
    r = client_local.post(f"{_p(workspace)}/areas/new", {"name": "Backend"})
    body = r.content.decode()
    # Sidebar area nav OOB (existing) + widget OOB (new) both present.
    assert 'id="area-nav"' in body
    assert 'id="onboarding-widget"' in body
    assert "hx-swap-oob" in body


@pytest.mark.django_db
def test_slice_create_oob_refreshes_widget(client_local, workspace):
    area = create_area(workspace, "Backend")
    r = client_local.post(f"{_p(workspace)}/areas/{area.slug}/slices", {"title": "Retry webhooks"})
    body = r.content.decode()
    assert 'id="onboarding-widget"' in body


@pytest.mark.django_db
def test_bite_create_oob_refreshes_widget(client_local, workspace):
    area = create_area(workspace, "Backend")
    sl = create_slice(area, "Retry webhooks", status="idea")
    r = client_local.post(f"{_p(workspace)}/slices/{sl.id}/bites", {"title": "Add backoff"})
    body = r.content.decode()
    assert 'id="onboarding-widget"' in body


@pytest.mark.django_db
def test_no_widget_oob_once_onboarding_complete(client_local, workspace):
    # A workspace that already dismissed onboarding gets no widget OOB noise.
    workspace.onboarding_dismissed = True
    workspace.save(update_fields=["onboarding_dismissed"])
    r = client_local.post(f"{_p(workspace)}/areas/new", {"name": "Backend"})
    assert 'id="onboarding-widget"' not in r.content.decode()
