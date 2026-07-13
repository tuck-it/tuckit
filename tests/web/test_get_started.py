import pytest

from tuckit.core.models import ApiToken, Area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_checklist_shows_on_fresh_home(client_local):
    body = client_local.get("/").content.decode()
    assert "Get started" in body
    assert "Connect your AI agent" in body


@pytest.mark.django_db
def test_checklist_hidden_when_all_done(client_local, workspace):
    ApiToken.objects.create(workspace=workspace, name="a", token_hash="x")
    default = Area.objects.get(workspace=workspace, is_triage=False)
    create_slice(default, "real", status="planned")
    body = client_local.get("/").content.decode()
    assert "Get started" not in body


@pytest.mark.django_db
def test_dismiss_hides_checklist(client_local, workspace):
    r = client_local.post("/onboarding/dismiss")
    assert r.status_code in (200, 204, 302)
    workspace.refresh_from_db()
    assert workspace.onboarding_dismissed is True
    assert "Get started" not in client_local.get("/").content.decode()
