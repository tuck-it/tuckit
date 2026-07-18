import pytest
from django.test import override_settings

from tuckit.core.models import Area, Org, User

pytestmark = pytest.mark.django_db


def _signup(client, email, password="pw12345678"):
    return client.post("/login/", {"step": "register", "email": email, "password": password})


@override_settings(REGISTRATION_OPEN=True)
def test_self_service_signup_then_org_lands_on_home(client):
    _signup(client, "new@example.com")
    r = client.post("/orgs/", {"name": "Acme", "slug": "acme"})
    assert r.status_code == 302
    u = User.objects.get(email="new@example.com")
    org = Org.objects.get(members__user=u)
    assert r.headers["Location"] == f"/{org.slug}/"


@override_settings(REGISTRATION_OPEN=True)
def test_signup_creates_exactly_one_org_and_triage(client):
    """Regression: the flat app serves /<org_slug>/ (the Workspace model is gone),
    and a fresh org gets exactly one Triage Area."""
    _signup(client, "logical@example.com")
    r = client.post("/orgs/", {"name": "Logical Org", "slug": "logical-org"})
    assert r.status_code == 302
    assert r.headers["Location"] == "/logical-org/"
    u = User.objects.get(email="logical@example.com")
    orgs = Org.objects.filter(members__user=u)
    assert orgs.count() == 1
    org = orgs.get()
    assert org.slug == "logical-org"
    assert Area.objects.filter(org=org, is_triage=True).count() == 1
