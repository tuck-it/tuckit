import pytest

from tuckit.core.models import Area
from tuckit.core.services.areas import create_area


def _p(org):
    return f"/{org.slug}"


@pytest.mark.django_db
def test_area_create_persists_description(client_local, org):
    client_local.post(f"{_p(org)}/areas/new", {"name": "Backend", "description": "APIs and jobs"})
    a = Area.objects.get(org=org, name="Backend")
    assert a.description == "APIs and jobs"


@pytest.mark.django_db
def test_area_create_without_description_defaults_empty(client_local, org):
    client_local.post(f"{_p(org)}/areas/new", {"name": "Marketing"})
    a = Area.objects.get(org=org, name="Marketing")
    assert a.description == ""


@pytest.mark.django_db
def test_area_create_oob_refreshes_widget(client_local, org):
    r = client_local.post(f"{_p(org)}/areas/new", {"name": "Backend"})
    body = r.content.decode()
    # Sidebar area nav OOB (existing) + widget OOB (new) both present.
    assert 'id="area-nav"' in body
    assert 'id="onboarding-widget"' in body
    assert "hx-swap-oob" in body


@pytest.mark.django_db
def test_slice_create_oob_refreshes_widget(client_local, org):
    area = create_area(org, "Backend")
    r = client_local.post(f"{_p(org)}/areas/{area.slug}/slices", {"title": "Retry webhooks"})
    body = r.content.decode()
    assert 'id="onboarding-widget"' in body


@pytest.mark.django_db
def test_no_widget_oob_once_onboarding_complete(client_local, org):
    # An org that already dismissed onboarding gets no widget OOB noise.
    org.onboarding_dismissed = True
    org.save(update_fields=["onboarding_dismissed"])
    r = client_local.post(f"{_p(org)}/areas/new", {"name": "Backend"})
    assert 'id="onboarding-widget"' not in r.content.decode()


@pytest.mark.django_db
def test_step_create_oob_refreshes_widget(client_local, org):
    # Adding a step from the slice panel must refresh the widget OOB so the
    # Bite step ticks immediately (previously stale until a full reload). The
    # route is the slice's own now — there is no Plan to hang it off.
    from tuckit.core.services.slices import create_slice

    slice_ = create_slice(org, area=create_area(org, "Backend"), title="Retry webhooks")
    r = client_local.post(
        f"{_p(org)}/slices/{slice_.id}/steps", {"title": "Write the retry test"},
        HTTP_HX_REQUEST="true",
    )
    body = r.content.decode()
    assert 'id="onboarding-widget"' in body
    assert "hx-swap-oob" in body


@pytest.mark.django_db
def test_panel_mutation_no_widget_when_dismissed(client_local, org):
    # A panel mutation on a dismissed org appends no widget OOB noise.
    from tuckit.core.services.slices import create_slice

    org.onboarding_dismissed = True
    org.save(update_fields=["onboarding_dismissed"])
    slice_ = create_slice(org, area=create_area(org, "Backend"), title="Retry webhooks")
    r = client_local.post(
        f"{_p(org)}/slices/{slice_.id}/steps", {"title": "Write the retry test"},
        HTTP_HX_REQUEST="true",
    )
    assert 'id="onboarding-widget"' not in r.content.decode()
