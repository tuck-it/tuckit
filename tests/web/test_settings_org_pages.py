import pytest

from tuckit.core.models import Invitation, Org, OrgMember, User
from tuckit.core.services.orgs import create_workspace


@pytest.fixture
def ctx(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    member = User.objects.create(email="m@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    ws = create_workspace(org, "Product")
    client.force_login(owner)
    return client, org, owner, member, ws


@pytest.mark.django_db
def test_members_page_lists_members_and_invite_form(ctx):
    client, org, owner, member, ws = ctx
    Invitation.objects.create(org=org, email="p@x.com", role="member", token="t1")
    body = client.get(f"/{org.slug}/settings/members").content.decode()
    assert "o@a.com" in body and "m@a.com" in body
    assert 'class="settings-nav"' in body
    assert f'hx-post="/{org.slug}/settings/invites"' in body   # invite form at new path
    assert "p@x.com" in body


@pytest.mark.django_db
def test_workspaces_page_lists_and_creates(ctx):
    client, org, owner, member, ws = ctx
    body = client.get(f"/{org.slug}/settings/workspaces").content.decode()
    assert "Product" in body
    assert f'action="/{org.slug}/settings/workspaces/new"' in body


@pytest.mark.django_db
def test_danger_page_owner_only(ctx):
    client, org, owner, member, ws = ctx
    assert client.get(f"/{org.slug}/settings/danger").status_code == 200
    client.force_login(member)
    body = client.get(f"/{org.slug}/settings/danger").content.decode()
    assert "Delete organization" not in body   # member sees no delete control


@pytest.mark.django_db
def test_member_role_mutation_at_new_path(ctx):
    client, org, owner, member, ws = ctx
    om = OrgMember.objects.get(org=org, user=member)
    resp = client.post(f"/{org.slug}/settings/members/{om.id}/role", {"role": "admin"})
    assert resp.status_code == 200
    om.refresh_from_db()
    assert om.role == "admin"
