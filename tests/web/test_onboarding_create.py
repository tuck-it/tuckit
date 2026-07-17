import pytest

from tuckit.core.models import Workspace
from tuckit.core.services.areas import create_area


def _p(ws):
    return f"/{ws.org.slug}/{ws.slug}"


@pytest.mark.django_db
def test_area_create_oob_refreshes_widget(client_local, org):
    ws = Workspace.objects.get(org=org)
    r = client_local.post(f"{_p(ws)}/areas/new", {"name": "Backend"})
    body = r.content.decode()
    # Sidebar area nav OOB (existing) + widget OOB (new) both present.
    assert 'id="area-nav"' in body
    assert 'id="onboarding-widget"' in body
    assert "hx-swap-oob" in body


@pytest.mark.django_db
def test_slice_create_oob_refreshes_widget(client_local, org):
    ws = Workspace.objects.get(org=org)
    area = create_area(ws.org, "Backend")
    r = client_local.post(f"{_p(ws)}/areas/{area.slug}/slices", {"title": "Retry webhooks"})
    body = r.content.decode()
    assert 'id="onboarding-widget"' in body


@pytest.mark.django_db
def test_no_widget_oob_once_onboarding_complete(client_local, org):
    ws = Workspace.objects.get(org=org)
    # A workspace that already dismissed onboarding gets no widget OOB noise.
    ws.onboarding_dismissed = True
    ws.save(update_fields=["onboarding_dismissed"])
    r = client_local.post(f"{_p(ws)}/areas/new", {"name": "Backend"})
    assert 'id="onboarding-widget"' not in r.content.decode()
