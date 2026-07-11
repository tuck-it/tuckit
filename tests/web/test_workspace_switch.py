import pytest

from core.models import Org, OrgMember, User
from core.services.orgs import create_workspace


@pytest.fixture
def two_workspaces(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(username="o@a.com", email="o@a.com")
    user.set_password("pw123456")
    user.save()
    OrgMember.objects.create(user=user, org=org, role="owner")
    a = create_workspace(org, "Alpha")
    b = create_workspace(org, "Beta")
    return user, a, b


@pytest.mark.django_db
def test_switch_workspace_updates_session(client, two_workspaces):
    user, a, b = two_workspaces
    client.force_login(user)
    resp = client.post("/switch-workspace", {"workspace_id": b.id})
    assert resp.status_code == 302
    assert client.session["active_workspace_id"] == b.id


@pytest.mark.django_db
def test_switch_to_inaccessible_workspace_forbidden(client, two_workspaces):
    user, a, b = two_workspaces
    other_org = Org.objects.create(name="Other", slug="other")
    outsider_ws = create_workspace(other_org, "Foreign")
    client.force_login(user)
    resp = client.post("/switch-workspace", {"workspace_id": outsider_ws.id})
    assert resp.status_code == 403


@pytest.mark.django_db
def test_switch_with_malformed_id_forbidden(client, two_workspaces):
    user, a, b = two_workspaces
    client.force_login(user)
    resp = client.post("/switch-workspace", {"workspace_id": "not-a-number"})
    assert resp.status_code == 403
    # empty value too
    resp2 = client.post("/switch-workspace", {"workspace_id": ""})
    assert resp2.status_code == 403


@pytest.mark.django_db
def test_create_workspace_in_org(client, two_workspaces):
    user, a, b = two_workspaces
    client.force_login(user)
    resp = client.post("/workspaces/new", {"name": "Gamma"})
    assert resp.status_code == 302
    assert a.org.workspaces.filter(name="Gamma").exists()
