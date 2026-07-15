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
def test_org_home_is_browse_only(org_ctx):
    client, org, owner, member, ws = org_ctx
    client.force_login(owner)
    body = client.get(f"/{org.slug}/").content.decode()
    assert "Board" in body or ws.name in body                 # workspace grid present
    assert "m@a.com" not in body                              # members NOT here anymore
    assert "Delete organization" not in body                 # danger NOT here
    assert f'href="/{org.slug}/settings/general"' in body    # link into org settings


@pytest.mark.django_db
def test_org_home_shows_new_workspace_form_for_admin(org_ctx):
    client, org, owner, member, ws = org_ctx
    client.force_login(owner)
    body = client.get(f"/{org.slug}/").content.decode()
    assert f'action="/{org.slug}/settings/workspaces/new"' in body


@pytest.mark.django_db
def test_org_home_hides_new_workspace_form_for_member(org_ctx):
    client, org, owner, member, ws = org_ctx
    client.force_login(member)
    body = client.get(f"/{org.slug}/").content.decode()
    assert f'action="/{org.slug}/settings/workspaces/new"' not in body


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


@pytest.mark.django_db
def test_org_home_breadcrumb(org_ctx):
    client, org, owner, member, ws = org_ctx
    client.force_login(owner)
    body = client.get(f"/{org.slug}/").content.decode()
    assert 'class="crumbbar"' in body
    assert f'href="/{org.slug}/settings/account/organizations"' in body   # "My orgs" → overview
