import pytest

from core.models import Area, Org, OrgMember, User, Workspace
from core.services.orgs import (
    accessible_workspaces, user_can_access_workspace, is_org_admin, seat_count, create_workspace,
)


@pytest.fixture
def org_with_owner(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(username="o@a.com", email="o@a.com")
    OrgMember.objects.create(user=user, org=org, role="owner")
    return org, user


@pytest.mark.django_db
def test_create_workspace_sets_up_inbox_and_default(org_with_owner):
    org, _ = org_with_owner
    ws = create_workspace(org, "Board")
    assert ws.org == org
    assert Area.objects.filter(workspace=ws, is_inbox=True).count() == 1
    assert Area.objects.filter(workspace=ws, is_inbox=False, slug="default").exists()


@pytest.mark.django_db
def test_create_workspace_unique_slug_within_org(org_with_owner):
    org, _ = org_with_owner
    a = create_workspace(org, "Board")
    b = create_workspace(org, "Board")
    assert a.slug != b.slug


@pytest.mark.django_db
def test_access_helpers(org_with_owner):
    org, user = org_with_owner
    ws = create_workspace(org, "Board")
    assert user_can_access_workspace(user, ws) is True
    assert is_org_admin(user, org) is True
    assert seat_count(org) == 1

    outsider = User.objects.create(username="x@x.com", email="x@x.com")
    assert user_can_access_workspace(outsider, ws) is False
    assert is_org_admin(outsider, org) is False
    assert list(accessible_workspaces(user)) == [ws]
    assert list(accessible_workspaces(outsider)) == []
