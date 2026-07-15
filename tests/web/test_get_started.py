import pytest

from tuckit.core.models import ApiToken
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite


@pytest.mark.django_db
def test_checklist_shows_four_steps_on_fresh_home(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert "Get started" in body
    assert "Create your first Area" in body
    assert "Add your first Slice" in body
    assert "Break it into Bites" in body
    assert "Connect your agent" in body


@pytest.mark.django_db
def test_fresh_home_gates_slice_step(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    # no Area yet → the Slice step shows the gate hint, not a create form
    assert "Create an Area first." in body


@pytest.mark.django_db
def test_slice_form_appears_after_area(client_local, workspace):
    create_area(workspace, "Backend")
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert "/onboarding/slice" in body
    assert "Create an Area first." not in body


@pytest.mark.django_db
def test_checklist_hidden_when_all_done(client_local, workspace):
    area = create_area(workspace, "Backend")
    sl = create_slice(area, "Retry webhooks", status="planned")
    create_bite(sl, "Add backoff")
    ApiToken.objects.create(workspace=workspace, name="a", token_hash="x")
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert "Get started" not in body


@pytest.mark.django_db
def test_dismiss_hides_checklist(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    r = client_local.post(f"{p}/onboarding/dismiss")
    assert r.status_code in (200, 204, 302)
    workspace.refresh_from_db()
    assert workspace.onboarding_dismissed is True
    assert "Get started" not in client_local.get(f"{p}/").content.decode()
