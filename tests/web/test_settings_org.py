import re

import pytest
from django.urls import NoReverseMatch, reverse

from tuckit.core.models import ApiToken, Invitation, OAuthAccessToken, Org, OrgMember, User
from tuckit.core.services import oauth
from tuckit.core.services.tokens import generate_token, hash_token, list_tokens


def _login(client, user):
    client.force_login(user)


@pytest.fixture
def org_ctx(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    member = User.objects.create(email="m@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    return client, org, owner, member


@pytest.mark.django_db
def test_org_page_renders_for_owner(org_ctx):
    # Org home (/<org>/) is browse-only; members live at /<org>/settings/members
    # (see test_settings_org_pages.py::test_members_page_lists_members_and_invite_form).
    client, org, owner, member = org_ctx
    _login(client, owner)
    resp = client.get(f"/{org.slug}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Acme" in body


@pytest.mark.django_db
def test_org_only_settings_branch_works_for_member(org_ctx):
    # Proves the org-only route sets request.org and still renders the
    # sidebar chrome via the current_org fallback.
    client, org, owner, member = org_ctx
    _login(client, member)
    resp = client.get(f"/{org.slug}/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_org_page_requires_login(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    resp = client.get(f"/{org.slug}/")
    assert resp.status_code in (302, 404)  # anon -> login redirect


@pytest.mark.django_db
def test_nonmember_gets_404_on_other_org_home(org_ctx):
    client, org, owner, member = org_ctx
    other = Org.objects.create(name="Other", slug="other")
    stranger = User.objects.create(email="stranger@x.com")
    OrgMember.objects.create(user=stranger, org=other, role="owner")
    _login(client, owner)  # owner is NOT a member of `other`
    resp = client.get(f"/{other.slug}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_owner_renames_org(org_ctx):
    client, org, owner, member = org_ctx
    _login(client, owner)
    resp = client.post(f"/{org.slug}/settings/rename", {"name": "Beta"})
    assert resp.status_code == 200
    org.refresh_from_db()
    assert org.name == "Beta"


@pytest.mark.django_db
def test_member_cannot_rename_org(org_ctx):
    client, org, owner, member = org_ctx
    _login(client, member)
    resp = client.post(f"/{org.slug}/settings/rename", {"name": "Beta"})
    assert resp.status_code == 403
    org.refresh_from_db()
    assert org.name == "Acme"


@pytest.mark.django_db
def test_owner_changes_member_role(org_ctx):
    client, org, owner, member = org_ctx
    _login(client, owner)
    om = OrgMember.objects.get(org=org, user=member)
    resp = client.post(f"/{org.slug}/settings/members/{om.id}/role", {"role": "admin"})
    assert resp.status_code == 200
    om.refresh_from_db()
    assert om.role == "admin"


@pytest.mark.django_db
def test_admin_cannot_change_role(org_ctx):
    client, org, owner, member = org_ctx
    # promote member to admin first (as owner), then act as that admin
    OrgMember.objects.filter(org=org, user=member).update(role="admin")
    _login(client, member)
    om_owner = OrgMember.objects.get(org=org, user=owner)
    resp = client.post(f"/{org.slug}/settings/members/{om_owner.id}/role", {"role": "member"})
    assert resp.status_code == 403


@pytest.mark.django_db
def test_admin_removes_member(org_ctx):
    client, org, owner, member = org_ctx
    _login(client, owner)
    om = OrgMember.objects.get(org=org, user=member)
    resp = client.post(f"/{org.slug}/settings/members/{om.id}/remove")
    assert resp.status_code == 204
    assert not OrgMember.objects.filter(id=om.id).exists()


@pytest.mark.django_db
def test_cannot_remove_member_of_other_org(org_ctx):
    client, org, owner, member = org_ctx
    other = Org.objects.create(name="Other", slug="other")
    stranger = User.objects.create(email="s@s.com")
    om_other = OrgMember.objects.create(user=stranger, org=other, role="member")
    _login(client, owner)
    resp = client.post(f"/{org.slug}/settings/members/{om_other.id}/remove")
    assert resp.status_code == 404
    assert OrgMember.objects.filter(id=om_other.id).exists()


from tuckit.core.models import Org as OrgModel  # alias to avoid fixture shadow


@pytest.mark.django_db
def test_owner_deletes_org_when_has_another(org_ctx):
    client, org, owner, member = org_ctx
    # owner also belongs to a second org, so deleting the first is allowed
    other = OrgModel.objects.create(name="Personal", slug="personal")
    OrgMember.objects.create(user=owner, org=other, role="owner")
    _login(client, owner)
    resp = client.post(f"/{org.slug}/settings/delete")
    assert resp.status_code == 302
    assert not OrgModel.objects.filter(id=org.id).exists()


@pytest.mark.django_db
def test_owner_deletes_org_htmx_redirects(org_ctx):
    client, org, owner, member = org_ctx
    other = OrgModel.objects.create(name="Personal", slug="personal")
    OrgMember.objects.create(user=owner, org=other, role="owner")
    _login(client, owner)
    resp = client.post(f"/{org.slug}/settings/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert resp["HX-Redirect"] == "/orgs/"  # full browser navigation, not an in-place swap
    assert not OrgModel.objects.filter(id=org.id).exists()


@pytest.mark.django_db
def test_member_cannot_delete_org(org_ctx):
    client, org, owner, member = org_ctx
    _login(client, member)
    resp = client.post(f"/{org.slug}/settings/delete")
    assert resp.status_code == 403
    assert OrgModel.objects.filter(id=org.id).exists()


@pytest.mark.django_db
def test_invite_urls_use_viewed_org_not_session_fallback(org_ctx):
    # Regression: a user who administers TWO orgs has `active_org_id` in
    # session pointing at Org A. Viewing Org B's settings page must build invite
    # create/cancel URLs against Org B (the viewed org), never the session
    # fallback org (Org A). Otherwise creating/cancelling an invite on Org B's
    # page silently touches Org A's data.
    # NOTE: invite management now lives at /<org>/settings/members, not org home
    # (/<org>/), which is browse-only as of the settings-IA refactor.
    client, org_a, owner, member = org_ctx
    org_b = Org.objects.create(name="Beta", slug="orgb")
    OrgMember.objects.create(user=owner, org=org_b, role="owner")
    Invitation.objects.create(org=org_b, email="pending-b@x.com", role="member", token="tok-b")

    _login(client, owner)
    # Establish the session fallback as Org A.
    home = client.get(f"/{org_a.slug}/")
    assert home.status_code == 200
    assert client.session.get("active_org_id") == org_a.id

    resp = client.get(f"/{org_b.slug}/settings/members")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"/{org_b.slug}/settings/invites" in body
    assert f"/{org_a.slug}/settings/invites" not in body

    resp = client.post(f"/{org_b.slug}/settings/invites", {"email": "new@x.com", "role": "member"})
    assert resp.status_code == 200
    inv = Invitation.objects.get(email="new@x.com")
    assert inv.org_id == org_b.id


# --- settings IA merge (Task 8): the workspace-settings pages are gone; General,
# Agent, Shipped board and Danger are all org-scoped now. ---


@pytest.mark.django_db
def test_settings_root_redirects_to_org_general(client_local, org):
    resp = client_local.get(f"/{org.slug}/settings/")
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/{org.slug}/settings/general"


@pytest.mark.django_db
def test_org_general_edits_description(client_local, org):
    client_local.post(f"/{org.slug}/settings/rename", {"name": "Renamed", "description": "we ship"})
    org.refresh_from_db()
    assert org.name == "Renamed"
    assert org.description == "we ship"


@pytest.mark.django_db
def test_agent_page_is_org_scoped(client_local, org):
    assert reverse("web:settings_org_agent", args=[org.slug]) == f"/{org.slug}/settings/agent"
    assert client_local.get(f"/{org.slug}/settings/agent").status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("name", [
    "settings_org_workspaces", "workspace_create", "settings_ws_general",
    "workspace_rename", "settings_ws_agent", "settings_ws_shipped",
    "settings_ws_danger", "workspace_delete",
])
def test_workspace_settings_routes_are_gone(name):
    with pytest.raises(NoReverseMatch):
        reverse(f"web:{name}", args=["acme", "acme"])


@pytest.mark.django_db
def test_deleting_your_only_org_lands_on_the_picker(client_local, org):
    """The 'can't delete the last workspace' guard is gone with the model. Deleting
    your only ORG must still work and must not strand you on a dead URL."""
    resp = client_local.post(f"/{org.slug}/settings/delete", {"confirm": org.slug})

    assert Org.objects.count() == 0
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/orgs/"


@pytest.mark.django_db
def test_deleting_an_org_clears_the_stale_session_key(client_local, org):
    client_local.get(f"/{org.slug}/")
    assert client_local.session["active_org_id"] == org.id

    client_local.post(f"/{org.slug}/settings/delete", {"confirm": org.slug})

    assert client_local.session.get("active_org_id") is None


# --- agent tokens (moved from workspace to org scope) ---


@pytest.mark.django_db
def test_token_create_shows_raw_once(client_local, org):
    resp = client_local.post(f"/{org.slug}/settings/tokens", {"name": "Claude Code"}, HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert len(body) > 0  # raw token surfaced in the returned partial


@pytest.mark.django_db
def test_token_create_stores_only_hash_not_raw(client_local, org):
    resp = client_local.post(f"/{org.slug}/settings/tokens", {"name": "Claude Code"}, HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    token = ApiToken.objects.get(org=org, name="Claude Code")
    # the raw token appears in the one-time partial...
    match = re.search(r'class="token-value"[^>]*>([^<]+)<', body)
    assert match, "raw token should be shown once in the create partial"
    raw = match.group(1)
    assert hash_token(raw) == token.token_hash
    # ...but the stored row never holds the raw value itself
    assert token.token_hash != raw


@pytest.mark.django_db
def test_agent_page_lists_masked_tokens(client_local, org):
    token, raw = generate_token(org, "Existing")
    resp = client_local.get(f"/{org.slug}/settings/agent")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Existing" in body
    assert raw not in body  # never re-displayed on the list page
    assert token.token_hash[:8] in body  # masked/truncated hash shown instead


@pytest.mark.django_db
def test_token_revoke_removes_token(client_local, org):
    token, _ = generate_token(org, "to-remove")
    resp = client_local.post(f"/{org.slug}/settings/tokens/{token.id}/revoke", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert not ApiToken.objects.filter(id=token.id).exists()


@pytest.mark.django_db
def test_token_revoke_is_org_scoped(client_local, org):
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    token, _ = generate_token(other_org, "cli")
    resp = client_local.post(f"/{org.slug}/settings/tokens/{token.id}/revoke", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert ApiToken.objects.filter(id=token.id).exists()  # untouched: belongs to another org


@pytest.mark.django_db
def test_member_cannot_create_token(client_local, org):
    # `org` (via ensure_bootstrap) already has a "local-cli" token; assert the
    # forbidden request doesn't add a second one rather than that none exist.
    before = list(list_tokens(org))
    member = User.objects.create(email="m-tok@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    client_local.force_login(member)
    resp = client_local.post(f"/{org.slug}/settings/tokens", {"name": "sneaky"})
    assert resp.status_code == 403
    assert list(list_tokens(org)) == before


@pytest.mark.django_db
def test_member_cannot_revoke_token(client_local, org):
    token, _raw = generate_token(org, "existing")
    before = len(list(list_tokens(org)))
    member = User.objects.create(email="m-rev@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    client_local.force_login(member)
    resp = client_local.post(f"/{org.slug}/settings/tokens/{token.id}/revoke")
    assert resp.status_code == 403
    assert len(list(list_tokens(org))) == before


# --- oauth connected-apps disconnect (view-level security, mirrors the ApiToken
# revoke tests above) ---


@pytest.mark.django_db
def test_oauth_disconnect_is_org_scoped(client_local, org):
    # A client's OAuth access token lives in a DIFFERENT org (`other_org`).
    # POSTing that client_id through `org`'s disconnect URL must not touch it:
    # disconnect_app() filters by the *viewed* org, so this is a no-op (the
    # view always re-renders the (unchanged) connected-apps partial with 200).
    other_org = Org.objects.create(name="Other Org", slug="other-oauth-org")
    user = User.objects.get(email="local@tuckit.local")
    c = oauth.create_client("Sneaky App", ["http://localhost:9999/cb"])
    oauth.issue_tokens(c, user, other_org, "mcp")
    resp = client_local.post(f"/{org.slug}/settings/agent/apps/{c.client_id}/disconnect")
    assert resp.status_code == 200
    assert OAuthAccessToken.objects.filter(client=c, org=other_org).exists()


@pytest.mark.django_db
def test_member_cannot_disconnect_app(client_local, org):
    user = User.objects.get(email="local@tuckit.local")
    c = oauth.create_client("Some App", ["http://localhost:9999/cb"])
    oauth.issue_tokens(c, user, org, "mcp")
    member = User.objects.create(email="m-oauth@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    client_local.force_login(member)
    resp = client_local.post(f"/{org.slug}/settings/agent/apps/{c.client_id}/disconnect")
    assert resp.status_code == 403
    assert OAuthAccessToken.objects.filter(client=c, org=org).exists()


# --- shipped-board prefs (moved from workspace to org scope) ---


@pytest.mark.django_db
def test_shipped_board_prefs_updates(client_local, org):
    resp = client_local.post(f"/{org.slug}/settings/shipped-board/prefs", {"mode": "days", "limit": "30"})
    assert resp.status_code == 204
    org.refresh_from_db()
    assert org.shipped_board_mode == "days"
    assert org.shipped_board_limit == 30


@pytest.mark.django_db
def test_shipped_board_prefs_rejects_bad_mode(client_local, org):
    resp = client_local.post(f"/{org.slug}/settings/shipped-board/prefs", {"mode": "weeks", "limit": "5"})
    assert resp.status_code == 400


@pytest.mark.django_db
def test_shipped_board_prefs_rejects_out_of_range(client_local, org):
    resp = client_local.post(f"/{org.slug}/settings/shipped-board/prefs", {"mode": "count", "limit": "0"})
    assert resp.status_code == 400


@pytest.mark.django_db
def test_member_cannot_configure_shipped_board(client_local, org):
    member = User.objects.create(email="m-ship@a.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    client_local.force_login(member)
    resp = client_local.post(
        f"/{org.slug}/settings/shipped-board/prefs", {"mode": "days", "limit": "30"}
    )
    assert resp.status_code == 403
    org.refresh_from_db()
    assert org.shipped_board_mode == "count"
    assert org.shipped_board_limit == 8


# --- OAuth-first connect UX (agent access page) ---

@pytest.mark.django_db
def test_agent_page_leads_with_tokenless_oauth_command(client_local, org):
    body = client_local.get(f"/{org.slug}/settings/agent").content.decode()
    # ① Connect headline shows the tokenless command...
    assert "claude mcp add --transport http tuckit" in body
    assert "Connect your agent" in body
    # ...and the primary connect block carries no raw-token/Bearer instruction.
    connect = body.split("Access tokens")[0]  # everything above section ③
    assert "Authorization: Bearer" not in connect
    assert "&lt;token&gt;" not in connect


@pytest.mark.django_db
def test_agent_page_demotes_token_path_to_headless_section(client_local, org):
    body = client_local.get(f"/{org.slug}/settings/agent").content.decode()
    assert "Access tokens · Headless &amp; CI" in body
    # the Bearer command lives ONLY in the headless section (below ①)
    assert "Authorization: Bearer" in body
    assert body.index("Connect your agent") < body.index("Access tokens")


@pytest.mark.django_db
def test_agent_page_section_order_is_1_3_2(client_local, org):
    body = client_local.get(f"/{org.slug}/settings/agent").content.decode()
    i_connect = body.index("Connect your agent")
    i_tokens = body.index("Access tokens")
    i_apps = body.index("Connected apps")
    assert i_connect < i_tokens < i_apps  # 1 → 3 → 2


@pytest.mark.django_db
def test_agent_page_uses_tuckit_name_not_tuck_it(client_local, org):
    body = client_local.get(f"/{org.slug}/settings/agent").content.decode()
    assert "tuck-it" not in body


@pytest.mark.django_db
def test_agent_page_has_client_switcher_with_claude_tab(client_local, org):
    body = client_local.get(f"/{org.slug}/settings/agent").content.decode()
    assert "x-data=\"{client:'claude'}\"" in body
    for cid in ("claude", "cursor", "codex", "antigravity"):
        assert f"client==='{cid}'" in body
