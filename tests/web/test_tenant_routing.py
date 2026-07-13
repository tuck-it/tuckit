import pytest
from django.urls import resolve, reverse

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.orgs import create_workspace


@pytest.fixture
def two_orgs(client, db):
    u = User.objects.create(email="member@a.com")
    org_a = Org.objects.create(name="Acme", slug="acme")
    OrgMember.objects.create(user=u, org=org_a, role="owner")
    ws_a = create_workspace(org_a, "Design")
    org_b = Org.objects.create(name="Other", slug="other")   # u is NOT a member
    ws_b = create_workspace(org_b, "Board")
    client.force_login(u)
    return client, u, org_a, ws_a, org_b, ws_b


# NOTE: The full page-render 200 assertion (test_member_can_open_own_workspace)
# and prefixed-link ({% wurl %}) template assertions are intentionally deferred
# to the template-conversion task. Right now app templates still call
# {% url 'web:home' %} (no args) and reference routes that changed, so a real
# GET of /acme/<ws>/ would 500. This dispatch verifies the routing backend
# (URL resolution/reversing + middleware access control) render-free.


@pytest.mark.django_db
def test_home_url_resolves_and_reverses(two_orgs):
    _client, _u, _org_a, ws_a, *_ = two_orgs
    assert reverse("web:home", args=["acme", ws_a.slug]) == f"/acme/{ws_a.slug}/"
    assert resolve(f"/acme/{ws_a.slug}/").view_name == "web:home"


@pytest.mark.django_db
def test_nonmember_gets_404_not_403(two_orgs):
    client, u, _a, _wa, org_b, ws_b = two_orgs
    resp = client.get(f"/other/{ws_b.slug}/")
    assert resp.status_code == 404  # existence not revealed


@pytest.mark.django_db
def test_unknown_org_404(two_orgs):
    client, *_ = two_orgs
    assert client.get("/nope/whatever/").status_code == 404


@pytest.mark.django_db
def test_unknown_workspace_404(two_orgs):
    client, u, org_a, *_ = two_orgs
    assert client.get("/acme/ghost/").status_code == 404
