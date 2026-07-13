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


@pytest.mark.django_db
def test_home_url_resolves_and_reverses(two_orgs):
    _client, _u, _org_a, ws_a, *_ = two_orgs
    assert reverse("web:home", args=["acme", ws_a.slug]) == f"/acme/{ws_a.slug}/"
    assert resolve(f"/acme/{ws_a.slug}/").view_name == "web:home"


@pytest.mark.django_db
def test_member_can_open_own_workspace(two_orgs):
    client, u, org_a, ws_a, *_ = two_orgs
    resp = client.get(f"/acme/{ws_a.slug}/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_app_page_links_are_prefixed(two_orgs):
    client, u, org_a, ws_a, *_ = two_orgs
    body = client.get(f"/acme/{ws_a.slug}/").content.decode()
    # sidebar/home links must carry the /acme/<ws>/ prefix
    assert f"/acme/{ws_a.slug}/triage/" in body
    assert f"/acme/{ws_a.slug}/" in body


@pytest.mark.django_db
def test_switcher_renders_workspace_links(two_orgs):
    client, u, org_a, ws_a, *_ = two_orgs
    # give the user a second workspace to switch to
    from tuckit.core.services.orgs import create_workspace
    ws2 = create_workspace(org_a, "Marketing")
    body = client.get(f"/acme/{ws_a.slug}/").content.decode()
    assert f'href="/acme/{ws2.slug}/"' in body
    assert "web:switch_workspace" not in body  # no leftover tag


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
