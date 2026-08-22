"""Tests for the Slack install OAuth flow.

The callback is org-less because Slack will not carry a path parameter
through the OAuth round trip, so the org rides in the `state` parameter
instead. That state must be signed and verified: an unsigned or unverified
state would let anyone bind their own Slack workspace to somebody else's
org, which is the actual security property this suite exists to pin.
"""
import pytest
from django.core import signing
from django.utils import timezone

from tests.integrations.slack.test_events_endpoint import _reload_urlconf
from tuckit.integrations.slack.models import SlackInstall

pytestmark = pytest.mark.django_db

STATE_SALT = "slack-install"


@pytest.fixture(autouse=True)
def _configured(settings):
    # The callback route (/slack/oauth/callback) comes from
    # slack_urlpatterns(), which is only non-empty when Slack is configured
    # and is evaluated once, at import time -- see
    # test_events_endpoint._reload_urlconf for the full explanation of why a
    # bare `settings` fixture is not enough to make the route reachable. The
    # connect page itself lives in the ordinary, unconditionally-mounted
    # org-scoped settings patterns, so only the callback needs this, but
    # reloading unconditionally here keeps this fixture simple and matches
    # what test_events_endpoint.py already does.
    settings.SLACK_CLIENT_ID = "1.2"
    settings.SLACK_CLIENT_SECRET = "s"
    settings.SLACK_SIGNING_SECRET = "sign"
    _reload_urlconf()
    yield
    _reload_urlconf()


def test_begin_redirects_to_slack_with_a_signed_state(client_local, org):
    r = client_local.get(f"/{org.slug}/settings/slack/connect")
    assert r.status_code == 302
    assert r["Location"].startswith("https://slack.com/oauth/v2/authorize")
    assert "state=" in r["Location"]


def test_begin_scopes_exclude_the_forbidden_ones(client_local, org):
    """The slice constraints forbid users:read.email, message.channels,
    message.im and reactions:write. A wrong implementation that widened
    BOT_SCOPES would still redirect successfully, so this has to check the
    actual scope list rather than just the status code."""
    from urllib.parse import parse_qs, urlparse

    r = client_local.get(f"/{org.slug}/settings/slack/connect")
    query = parse_qs(urlparse(r["Location"]).query)
    scopes = query["scope"][0].split(",")
    for forbidden in ("users:read.email", "message.channels", "message.im", "reactions:write"):
        assert forbidden not in scopes


def test_callback_stores_the_install(client_local, org, monkeypatch):
    monkeypatch.setattr(
        "tuckit.integrations.slack.views.exchange_oauth_code",
        lambda **kw: {
            "ok": True, "access_token": "xoxb-1",
            "team": {"id": "T1", "name": "Acme"},
            "bot_user_id": "U0",
        },
    )
    state = signing.dumps({"org_id": org.id}, salt=STATE_SALT)
    r = client_local.get(f"/slack/oauth/callback?code=abc&state={state}")
    assert r.status_code == 302
    install = SlackInstall.objects.get(org=org)
    assert install.team_id == "T1"
    assert install.bot_token == "xoxb-1"


def test_a_tampered_state_is_refused(client_local):
    r = client_local.get("/slack/oauth/callback?code=abc&state=not-signed")
    assert r.status_code == 400
    assert SlackInstall.objects.count() == 0


def test_a_missing_state_is_refused_rather_than_crashing(client_local):
    """A wrong implementation that skipped verification entirely (e.g. just
    trusted request.GET) would 500 or KeyError on a malformed/missing state
    instead of answering 400 -- that would still leave test_a_tampered_
    state_is_refused's sibling failing loudly, but a bare `except Exception:
    return 400` around unrelated code could accidentally swallow the crash
    and make this pass anyway, so it's asserted with no code path skipped."""
    r = client_local.get("/slack/oauth/callback")
    assert r.status_code == 400
    assert SlackInstall.objects.count() == 0


def test_a_member_of_a_different_org_cannot_use_anothers_state(client, other_org_member, org):
    """The actual security property: a validly SIGNED state naming `org` is
    still not enough on its own to complete the install. The user who lands
    on the callback must also be an active member of the org the state
    names -- otherwise anyone who ever got hold of a legitimate install link
    (a forwarded message, a shared screen, browser history) could bind their
    own Slack workspace to an org they have never belonged to.

    other_org_member is only a member of `other_org`, not `org`, so this
    proves the callback checks membership independently of the signature.
    """
    client.force_login(other_org_member.user)
    state = signing.dumps({"org_id": org.id}, salt=STATE_SALT)
    r = client.get(f"/slack/oauth/callback?code=abc&state={state}")
    assert r.status_code == 400
    assert SlackInstall.objects.count() == 0


def test_a_departed_member_cannot_complete_the_install(client_local, org, member):
    """OrgMember.objects is the active manager (ended_at__isnull=True). If
    the callback reached past it to all_objects, someone who has since left
    the org could still complete an install they started (or a state they
    still held) before leaving."""
    member.ended_at = timezone.now()
    member.save(update_fields=["ended_at"])
    state = signing.dumps({"org_id": org.id}, salt=STATE_SALT)
    r = client_local.get(f"/slack/oauth/callback?code=abc&state={state}")
    assert r.status_code == 400
    assert SlackInstall.objects.count() == 0


def test_settings_page_shows_connect_when_not_installed(client_local, org):
    r = client_local.get(f"/{org.slug}/settings/slack")
    assert r.status_code == 200
    assert b"Connect to Slack" in r.content


def test_settings_page_shows_the_team_when_installed(client_local, org, member):
    SlackInstall.objects.create(
        org=org, team_id="T1", team_name="Acme", bot_token="xoxb-1",
        bot_user_id="U0", installed_by=member,
    )
    r = client_local.get(f"/{org.slug}/settings/slack")
    assert r.status_code == 200
    assert b"Acme" in r.content
    assert b"Disconnect" in r.content


def test_disconnect_removes_the_install(client_local, org, member):
    SlackInstall.objects.create(
        org=org, team_id="T1", team_name="Acme", bot_token="xoxb-1",
        bot_user_id="U0", installed_by=member,
    )
    r = client_local.post(f"/{org.slug}/settings/slack/disconnect")
    assert r.status_code in (302, 204)
    assert SlackInstall.objects.filter(org=org).count() == 0
