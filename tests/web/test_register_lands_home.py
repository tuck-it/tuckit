import pytest
from django.test import override_settings

from tuckit.core.models import Area, Org, User, Workspace


@pytest.mark.django_db
@override_settings(REGISTRATION_OPEN=True)
def test_self_service_register_lands_on_home(client):
    r = client.post("/register/", {
        "email": "new@example.com", "org_name": "Acme",
        "slug": "acme", "password": "pw12345678",
    })
    assert r.status_code == 302
    u = User.objects.get(email="new@example.com")
    org = Org.objects.get(members__user=u)
    assert r.headers["Location"] == f"/{org.slug}/"


@pytest.mark.django_db
@override_settings(REGISTRATION_OPEN=True)
def test_self_service_register_creates_exactly_one_org_and_triage_no_workspace(client):
    """Regression for the original bug: signup used to create an Org AND an
    auto-named Workspace, redirecting to /<org_slug>/<workspace_slug>/ instead
    of the flat /<org_slug>/ the app now serves. Assert the fix: one Org, one
    Triage Area, and zero Workspace rows for the new user."""
    r = client.post("/register/", {
        "email": "logical@example.com", "org_name": "Logical Org",
        "slug": "logical-org", "password": "pw12345678",
    })
    assert r.status_code == 302
    assert r.headers["Location"] == "/logical-org/"
    u = User.objects.get(email="logical@example.com")
    orgs = Org.objects.filter(members__user=u)
    assert orgs.count() == 1
    org = orgs.get()
    assert org.slug == "logical-org"
    assert Area.objects.filter(org=org, is_triage=True).count() == 1
    assert Workspace.objects.filter(org=org).count() == 0
