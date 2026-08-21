from urllib.parse import urlparse, parse_qs

import pytest

from tuckit.core.models import Org, User, OrgMember, OAuthAuthorizationCode
from tuckit.core.services import oauth


@pytest.fixture
def setup(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user(email="a@b.com", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    client_obj = oauth.create_client("Claude Code", ["http://localhost:9999/cb"])
    return org, user, client_obj


def _params(client_obj, verifier="verifier-1234567890-abcdefghij"):
    return {
        "response_type": "code",
        "client_id": client_obj.client_id,
        "redirect_uri": "http://localhost:9999/cb",
        "code_challenge": oauth.s256(verifier),
        "code_challenge_method": "S256",
        "state": "xyz",
        "scope": "mcp",
    }


@pytest.mark.django_db
def test_authorize_requires_login(client, setup):
    _org, _user, client_obj = setup
    resp = client.get("/oauth/authorize", _params(client_obj))
    assert resp.status_code == 302 and "/login" in resp["Location"]


@pytest.mark.django_db
def test_authorize_get_renders_consent(client, setup):
    _org, user, client_obj = setup
    client.force_login(user)
    resp = client.get("/oauth/authorize", _params(client_obj))
    assert resp.status_code == 200
    assert b"Claude Code" in resp.content


@pytest.mark.django_db
def test_authorize_bad_redirect_uri_shows_error_no_redirect(client, setup):
    _org, user, client_obj = setup
    client.force_login(user)
    p = _params(client_obj)
    p["redirect_uri"] = "http://evil/cb"
    resp = client.get("/oauth/authorize", p)
    assert resp.status_code == 400  # error page, NOT a redirect


@pytest.mark.django_db
def test_authorize_post_issues_code(client, setup):
    org, user, client_obj = setup
    client.force_login(user)
    p = _params(client_obj)
    p["org_id"] = str(org.id)
    resp = client.post("/oauth/authorize", p)
    assert resp.status_code == 302
    q = parse_qs(urlparse(resp["Location"]).query)
    assert q["state"] == ["xyz"]
    assert q["code"]
    assert OAuthAuthorizationCode.objects.count() == 1


@pytest.fixture
def no_org_user(db):
    """A brand-new account: signed up, belongs to no org. This is what
    create_account() produces and what the OAuth flow currently dead-ends on."""
    user = User.objects.create_user(email="new@b.com", password="pw123456")
    client_obj = oauth.create_client("Claude Code", ["http://localhost:9999/cb"])
    return user, client_obj


@pytest.mark.django_db
def test_authorize_post_creates_workspace_and_issues_code(client, no_org_user):
    user, client_obj = no_org_user
    client.force_login(user)
    p = _params(client_obj)
    p["org_id"] = "__new__"
    p["org_name"] = "My App"
    resp = client.post("/oauth/authorize", p)
    assert resp.status_code == 302
    q = parse_qs(urlparse(resp["Location"]).query)
    assert q["code"]
    org = Org.objects.get(name="My App")
    assert org.slug  # create_org derives a unique slug on its own
    assert OrgMember.objects.filter(user=user, org=org, role="owner").exists()
    assert OAuthAuthorizationCode.objects.get().org == org


@pytest.mark.django_db
def test_authorize_post_blank_name_rerenders_consent_keeping_oauth_context(client, no_org_user):
    user, client_obj = no_org_user
    client.force_login(user)
    p = _params(client_obj)
    p["org_id"] = "__new__"
    p["org_name"] = "   "
    resp = client.post("/oauth/authorize", p)
    assert resp.status_code == 400
    assert Org.objects.count() == 0
    # The consent form comes back, not a dead-end error page: the whole OAuth
    # context has to survive or the user starts over from the client.
    assert resp.context["error"]
    assert resp.context["show_new"] is True
    assert resp.context["code_challenge"] == p["code_challenge"]
    assert resp.context["state"] == "xyz"
    assert resp.context["redirect_uri"] == "http://localhost:9999/cb"


@pytest.mark.django_db
def test_authorize_post_unknown_org_rerenders_consent(client, setup):
    _org, user, client_obj = setup
    client.force_login(user)
    p = _params(client_obj)
    p["org_id"] = "999999"
    resp = client.post("/oauth/authorize", p)
    assert resp.status_code == 400
    assert resp.context["error"]
    assert resp.context["client"] == client_obj


@pytest.mark.django_db
def test_authorize_get_never_creates_an_org(client, no_org_user):
    user, client_obj = no_org_user
    client.force_login(user)
    resp = client.get("/oauth/authorize", _params(client_obj))
    assert resp.status_code == 200
    assert Org.objects.count() == 0


@pytest.mark.django_db
def test_authorize_bad_redirect_uri_still_wins_over_workspace_creation(client, no_org_user):
    """The open-redirector guard runs first. A POST that would otherwise create
    a workspace must be rejected on the unverified redirect_uri instead."""
    user, client_obj = no_org_user
    client.force_login(user)
    p = _params(client_obj)
    p["redirect_uri"] = "http://evil/cb"
    p["org_id"] = "__new__"
    p["org_name"] = "My App"
    resp = client.post("/oauth/authorize", p)
    assert resp.status_code == 400
    assert Org.objects.count() == 0


@pytest.mark.django_db
def test_consent_offers_creating_a_workspace_when_user_has_none(client, no_org_user):
    user, client_obj = no_org_user
    client.force_login(user)
    resp = client.get("/oauth/authorize", _params(client_obj))
    assert resp.status_code == 200
    assert resp.context["show_new"] is True
    body = resp.content.decode()
    assert 'value="__new__"' in body
    assert 'name="org_name"' in body


@pytest.mark.django_db
def test_consent_offers_creating_a_workspace_alongside_existing_ones(client, setup):
    org, user, client_obj = setup
    client.force_login(user)
    resp = client.get("/oauth/authorize", _params(client_obj))
    body = resp.content.decode()
    assert resp.context["show_new"] is False
    assert org.name in body
    assert 'value="__new__"' in body  # a second workspace is reachable from here too


@pytest.mark.django_db
def test_consent_does_not_mention_plans(client, setup):
    """Plan was deleted by the two-layer model; the consent copy still said it."""
    _org, user, client_obj = setup
    client.force_login(user)
    resp = client.get("/oauth/authorize", _params(client_obj))
    assert "Plans" not in resp.content.decode()
