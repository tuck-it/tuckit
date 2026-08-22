"""Tests for the Slack install OAuth flow.

The callback is org-less because Slack will not carry a path parameter
through the OAuth round trip, so the org rides in the `state` parameter
instead. That state must be signed and verified: an unsigned or unverified
state would let anyone bind their own Slack workspace to somebody else's
org, which is the actual security property this suite exists to pin.

Connecting (or re-pointing) an org's Slack workspace is an org-level
configuration change -- the same class of action as disconnecting one -- so
every path that can create or change a SlackInstall is admin-gated, and a
re-point onto a different team_id is never applied without confirmation.
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


def _signed_state(org_id):
    return signing.dumps({"org_id": org_id}, salt=STATE_SALT)


def _mock_exchange(monkeypatch, *, team_id="T1", team_name="Acme", token="xoxb-1"):
    monkeypatch.setattr(
        "tuckit.integrations.slack.views.exchange_oauth_code",
        lambda **kw: {
            "ok": True, "access_token": token,
            "team": {"id": team_id, "name": team_name},
            "bot_user_id": "U0",
        },
    )


# --- begin: happy path + scope floor ---

def test_begin_redirects_to_slack_with_a_signed_state(client_local, org):
    """client_local is bound to `member`, whose default role is "owner" --
    an admin, so this is the admin happy path."""
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


def test_begin_refuses_a_non_admin_member(client, org, member_factory):
    """Connecting Slack is an org-level configuration change, gated the same
    way slack_disconnect already was. A plain member must not reach the
    Connect button's target at all."""
    non_admin = member_factory(org, role="member")
    client.force_login(non_admin.user)
    r = client.get(f"/{org.slug}/settings/slack/connect")
    assert r.status_code == 403


# --- callback: happy path, admin gate, cross-org, departed member ---

def test_callback_stores_the_install(client_local, org, monkeypatch):
    _mock_exchange(monkeypatch)
    r = client_local.get(f"/slack/oauth/callback?code=abc&state={_signed_state(org.id)}")
    assert r.status_code == 302
    install = SlackInstall.objects.get(org=org)
    assert install.team_id == "T1"
    assert install.bot_token == "xoxb-1"


def test_callback_refuses_a_non_admin_member(client, org, member_factory, monkeypatch):
    """A non-admin who nonetheless holds a validly-signed state for their own
    org (e.g. it was minted before they were demoted, or handed to them by
    someone else) must still be refused. Membership alone is not enough --
    this is what distinguishes the admin gate from the membership check
    covered by the cross-org and departed-member tests below."""
    _mock_exchange(monkeypatch)
    non_admin = member_factory(org, role="member")
    client.force_login(non_admin.user)
    r = client.get(f"/slack/oauth/callback?code=abc&state={_signed_state(org.id)}")
    assert r.status_code == 403
    assert SlackInstall.objects.count() == 0


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
    r = client.get(f"/slack/oauth/callback?code=abc&state={_signed_state(org.id)}")
    assert r.status_code == 400
    assert SlackInstall.objects.count() == 0


def test_a_departed_member_cannot_complete_the_install(client_local, org, member):
    """OrgMember.objects is the active manager (ended_at__isnull=True). If
    the callback reached past it to all_objects, someone who has since left
    the org could still complete an install they started (or a state they
    still held) before leaving."""
    member.ended_at = timezone.now()
    member.save(update_fields=["ended_at"])
    r = client_local.get(f"/slack/oauth/callback?code=abc&state={_signed_state(org.id)}")
    assert r.status_code == 400
    assert SlackInstall.objects.count() == 0


# --- re-point: an existing install is never silently replaced ---

def test_a_different_team_id_does_not_silently_replace_the_install(client_local, org, member, monkeypatch):
    """The spec promise: 'One team_id maps to exactly one org, enforced by a
    unique constraint; re-pointing an existing install asks first.' A wrong
    implementation using a plain update_or_create() would pass every other
    test in this file (they only ever exercise a single team_id) while
    silently moving a working integration's bot token, and therefore where
    every card and unfurl goes, out from under whoever was relying on it."""
    SlackInstall.objects.create(
        org=org, team_id="T-OLD", team_name="Old Co", bot_token="xoxb-old",
        bot_user_id="U-OLD", installed_by=member,
    )
    _mock_exchange(monkeypatch, team_id="T-NEW", team_name="New Co", token="xoxb-new")
    r = client_local.get(f"/slack/oauth/callback?code=abc&state={_signed_state(org.id)}")
    assert r.status_code == 302
    install = SlackInstall.objects.get(org=org)
    assert install.team_id == "T-OLD"
    assert install.bot_token == "xoxb-old"


def test_the_same_team_id_reconnecting_is_not_treated_as_a_repoint(client_local, org, member, monkeypatch):
    """Re-authing the same workspace (token rotation, re-granting scopes) is
    not a re-point and must not require confirmation."""
    SlackInstall.objects.create(
        org=org, team_id="T1", team_name="Acme", bot_token="xoxb-old",
        bot_user_id="U-OLD", installed_by=member,
    )
    _mock_exchange(monkeypatch, team_id="T1", team_name="Acme", token="xoxb-new")
    r = client_local.get(f"/slack/oauth/callback?code=abc&state={_signed_state(org.id)}")
    assert r.status_code == 302
    install = SlackInstall.objects.get(org=org)
    assert install.bot_token == "xoxb-new"


def test_confirming_the_pending_switch_replaces_the_install(client_local, org, member, monkeypatch):
    SlackInstall.objects.create(
        org=org, team_id="T-OLD", team_name="Old Co", bot_token="xoxb-old",
        bot_user_id="U-OLD", installed_by=member,
    )
    _mock_exchange(monkeypatch, team_id="T-NEW", team_name="New Co", token="xoxb-new")
    client_local.get(f"/slack/oauth/callback?code=abc&state={_signed_state(org.id)}")
    r = client_local.post(f"/{org.slug}/settings/slack/confirm")
    assert r.status_code in (302, 204)
    install = SlackInstall.objects.get(org=org)
    assert install.team_id == "T-NEW"
    assert install.bot_token == "xoxb-new"


def test_a_non_admin_cannot_confirm_a_switch(client, org, member, member_factory):
    """The confirm endpoint is the fourth path that can write a SlackInstall
    (alongside begin, callback and disconnect) and is gated the same way --
    a plain member posting to it directly must be refused regardless of
    whatever their own session does or doesn't have pending."""
    SlackInstall.objects.create(
        org=org, team_id="T-OLD", team_name="Old Co", bot_token="xoxb-old",
        bot_user_id="U-OLD", installed_by=member,
    )
    non_admin = member_factory(org, role="member")
    client.force_login(non_admin.user)
    r = client.post(f"/{org.slug}/settings/slack/confirm")
    assert r.status_code == 403
    install = SlackInstall.objects.get(org=org)
    assert install.team_id == "T-OLD"


# --- settings page ---

def test_settings_page_shows_connect_when_not_installed(client_local, org):
    r = client_local.get(f"/{org.slug}/settings/slack")
    assert r.status_code == 200
    assert b"Connect to Slack" in r.content


def test_settings_page_hides_connect_from_a_non_admin(client, org, member_factory):
    non_admin = member_factory(org, role="member")
    client.force_login(non_admin.user)
    r = client.get(f"/{org.slug}/settings/slack")
    assert r.status_code == 200
    assert b"Connect to Slack" not in r.content


def test_settings_page_shows_the_team_when_installed(client_local, org, member):
    SlackInstall.objects.create(
        org=org, team_id="T1", team_name="Acme", bot_token="xoxb-1",
        bot_user_id="U0", installed_by=member,
    )
    r = client_local.get(f"/{org.slug}/settings/slack")
    assert r.status_code == 200
    assert b"Acme" in r.content
    assert b"Disconnect" in r.content


# --- disconnect ---

def test_disconnect_removes_the_install(client_local, org, member):
    SlackInstall.objects.create(
        org=org, team_id="T1", team_name="Acme", bot_token="xoxb-1",
        bot_user_id="U0", installed_by=member,
    )
    r = client_local.post(f"/{org.slug}/settings/slack/disconnect")
    assert r.status_code in (302, 204)
    assert SlackInstall.objects.filter(org=org).count() == 0
