import pytest

from tuckit.core.models import OrgMember, User, Workspace
from tuckit.core.services.orgs import create_org


def _login(client, user, ws):
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()


@pytest.fixture
def acct_ctx(client, db):
    user = User.objects.create(email="u@u.com")
    org_a, ws_a = create_org(user, name="Alpha")
    org_b, ws_b = create_org(user, name="Beta")
    return client, user, org_a, ws_a, org_b, ws_b


@pytest.mark.django_db
def test_account_page_lists_my_orgs(acct_ctx):
    client, user, org_a, ws_a, org_b, ws_b = acct_ctx
    _login(client, user, ws_a)
    resp = client.get("/settings/account")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Alpha" in body and "Beta" in body
    assert "u@u.com" in body                       # email shown


@pytest.mark.django_db
def test_create_org_from_account(acct_ctx):
    client, user, org_a, ws_a, org_b, ws_b = acct_ctx
    _login(client, user, ws_a)
    resp = client.post("/settings/account/orgs", {"name": "Gamma"})
    assert resp.status_code in (204, 302)          # navigates to home
    assert OrgMember.objects.filter(user=user, org__name="Gamma", role="owner").exists()
    # active workspace switched to the new org's workspace
    new_ws = Workspace.objects.get(org__name="Gamma")
    assert client.session.get("active_workspace_id") == new_ws.id


@pytest.mark.django_db
def test_leave_org_from_account(acct_ctx):
    client, user, org_a, ws_a, org_b, ws_b = acct_ctx
    # create_org makes `user` the SOLE owner of org_b, so leaving it would hit
    # the sole-owner guard regardless of the account-page flow being tested
    # here. Add a co-owner so this test exercises a clean, allowed leave.
    co_owner = User.objects.create(email="c@c.com")
    OrgMember.objects.create(user=co_owner, org=org_b, role="owner")
    _login(client, user, ws_a)                     # currently in Alpha
    om_b = OrgMember.objects.get(user=user, org=org_b)
    resp = client.post(f"/settings/account/orgs/{org_b.id}/leave")
    assert resp.status_code in (204, 302)
    assert not OrgMember.objects.filter(id=om_b.id).exists()


@pytest.mark.django_db
def test_leave_current_org_clears_active_workspace(acct_ctx):
    client, user, org_a, ws_a, org_b, ws_b = acct_ctx
    # Same fixture reality as above: `user` is the sole owner of org_a, so a
    # co-owner is needed for the leave itself to be allowed — this test's
    # intent is to verify the *session-clearing* behavior on a successful
    # leave, not to re-verify the sole-owner guard (covered separately).
    co_owner = User.objects.create(email="d@d.com")
    OrgMember.objects.create(user=co_owner, org=org_a, role="owner")
    _login(client, user, ws_a)                     # active = Alpha's ws
    client.post(f"/settings/account/orgs/{org_a.id}/leave")
    assert not OrgMember.objects.filter(user=user, org=org_a).exists()
    assert client.session.get("active_workspace_id") != ws_a.id


@pytest.mark.django_db
def test_leave_sole_owner_returns_400(acct_ctx):
    client, user, org_a, ws_a, org_b, ws_b = acct_ctx
    # make org_a have a second workspace-less owner? No — sole owner of BOTH.
    # user is sole owner of org_a and org_b; leaving org_a is allowed only if a
    # second owner exists. Here user is sole owner, so it must be rejected.
    _login(client, user, ws_b)
    resp = client.post(f"/settings/account/orgs/{org_a.id}/leave")
    assert resp.status_code == 400
    assert OrgMember.objects.filter(user=user, org=org_a).exists()


@pytest.mark.django_db
def test_leave_org_not_a_member_404s(acct_ctx):
    client, user, org_a, ws_a, org_b, ws_b = acct_ctx
    stranger_owner = User.objects.create(email="s@s.com")
    foreign, _ = create_org(stranger_owner, name="Foreign")
    _login(client, user, ws_a)
    resp = client.post(f"/settings/account/orgs/{foreign.id}/leave")
    assert resp.status_code == 404
    assert OrgMember.objects.filter(user=stranger_owner, org=foreign).exists()


@pytest.mark.django_db
def test_account_page_open_links_target_other_orgs(acct_ctx):
    # The old POST "switch org" flow is now an <a href> to that org's first
    # workspace. The current org shows no Open link; the other shows a prefixed one.
    client, user, org_a, ws_a, org_b, ws_b = acct_ctx
    _login(client, user, ws_a)
    body = client.get("/settings/account").content.decode()
    assert f'href="/{org_b.slug}/{ws_b.slug}/"' in body
    assert "web:account_org_open" not in body  # no leftover POST-switch tag
