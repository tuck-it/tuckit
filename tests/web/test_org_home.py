import pytest

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.orgs import create_workspace


@pytest.fixture
def org_ctx(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    member = User.objects.create(email="m@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    ws = create_workspace(org, "Board")
    return client, org, owner, member, ws


@pytest.mark.django_db
def test_org_home_renders_members_and_workspaces(org_ctx):
    client, org, owner, member, ws = org_ctx
    client.force_login(owner)
    resp = client.get(f"/{org.slug}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Acme" in body
    assert "o@a.com" in body and "m@a.com" in body
    assert "Board" in body
    # Opening a workspace links to its home
    assert f'href="/{org.slug}/{ws.slug}/"' in body


@pytest.mark.django_db
def test_org_home_shows_new_workspace_form_for_admin(org_ctx):
    client, org, owner, member, ws = org_ctx
    client.force_login(owner)
    body = client.get(f"/{org.slug}/").content.decode()
    assert f'action="/settings/{org.slug}/workspaces/new"' in body


@pytest.mark.django_db
def test_org_home_hides_new_workspace_form_for_member(org_ctx):
    client, org, owner, member, ws = org_ctx
    client.force_login(member)
    body = client.get(f"/{org.slug}/").content.decode()
    assert f'action="/settings/{org.slug}/workspaces/new"' not in body


@pytest.mark.django_db
def test_org_home_404_for_nonmember(org_ctx):
    client, org, owner, member, ws = org_ctx
    other = Org.objects.create(name="Other", slug="other")
    stranger = User.objects.create(email="s@s.com")
    OrgMember.objects.create(user=stranger, org=other, role="owner")
    client.force_login(stranger)  # not a member of `acme`
    resp = client.get(f"/{org.slug}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_org_home_requires_login(org_ctx):
    client, org, owner, member, ws = org_ctx
    resp = client.get(f"/{org.slug}/")
    assert resp.status_code in (302, 404)
