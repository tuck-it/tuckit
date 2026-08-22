"""Tests for identity resolution and the connect flow.

resolve_member is the access gate for the whole integration: everything a
Slack user can write through the bot is attributed through the OrgMember it
returns. The load-bearing case is test_a_departed_member_no_longer_resolves
-- see its docstring.
"""
import hashlib
import hmac
import json
import time

import pytest
from django.utils import timezone

from tests.integrations.slack.test_events_endpoint import _reload_urlconf
from tuckit.integrations.slack.identity import connect_state, resolve_member
from tuckit.integrations.slack.models import SlackIdentity, SlackInstall

pytestmark = pytest.mark.django_db

SECRET = "test-signing-secret"


@pytest.fixture
def install(org):
    return SlackInstall.objects.create(org=org, team_id="T1", bot_token="x", bot_user_id="U0")


@pytest.fixture(autouse=True)
def _configured(settings):
    # slack_connect_begin, slack_connect_callback and slack_command all come
    # from slack_urlpatterns(), evaluated once at import time -- see
    # test_events_endpoint._reload_urlconf for why a bare `settings` fixture
    # is not enough to make the routes reachable.
    settings.SLACK_CLIENT_ID = "1.2"
    settings.SLACK_CLIENT_SECRET = "s"
    settings.SLACK_SIGNING_SECRET = SECRET
    _reload_urlconf()
    yield
    _reload_urlconf()


def _signed_command(body: dict, secret: str = SECRET):
    from urllib.parse import urlencode

    raw = urlencode(body).encode()
    ts = str(int(time.time()))
    base = b"v0:" + ts.encode() + b":" + raw
    sig = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return raw, ts, sig


# --- resolve_member: the access gate ---


def test_unknown_slack_user_resolves_to_none(install):
    assert resolve_member(install, "U-unknown") is None


def test_known_slack_user_resolves_to_the_member(install, member):
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    assert resolve_member(install, "U9") == member


def test_a_departed_member_no_longer_resolves(install, member):
    """The whole access gate, in one test.

    The FK still points at the row -- base_manager_name is all_objects -- so a
    naive select_related would return this person and let them keep writing
    through Slack after leaving the org. Slice 232 is that defect on the MCP
    side; this test is why it does not happen twice.
    """
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    member.ended_at = timezone.now()
    member.save(update_fields=["ended_at"])

    assert resolve_member(install, "U9") is None


# --- connect callback: the only way an identity gets created ---


def test_connect_callback_links_the_logged_in_user(client_local, install, member):
    r = client_local.get(f"/slack/connect/done?state={connect_state(install, 'U9')}")
    assert r.status_code == 200
    assert resolve_member(install, "U9") == member


def test_connect_callback_refuses_an_unsigned_state(client_local, install):
    r = client_local.get("/slack/connect/done?state=forged")
    assert r.status_code == 400
    assert SlackIdentity.objects.count() == 0


def test_a_user_outside_the_org_cannot_link(client, install, other_org_member):
    client.force_login(other_org_member.user)
    r = client.get(f"/slack/connect/done?state={connect_state(install, 'U9')}")
    assert r.status_code == 403
    assert SlackIdentity.objects.count() == 0


def test_a_departed_member_cannot_link_through_the_callback(client, install, member):
    """The connect callback itself must not be a second way around the same
    gate resolve_member enforces: OrgMember.objects (the active manager) is
    what the callback filters through, so someone who has left cannot revive
    their own link by clicking the button again."""
    member.ended_at = timezone.now()
    member.save(update_fields=["ended_at"])
    client.force_login(member.user)
    r = client.get(f"/slack/connect/done?state={connect_state(install, 'U9')}")
    assert r.status_code == 403
    assert SlackIdentity.objects.count() == 0


def test_connect_callback_requires_login(client, install):
    """An anonymous visitor must not be able to link an identity at all --
    login_required is what makes "the person being logged into tuckit and
    clicking" the only path, per the slice's no-email-fallback constraint."""
    r = client.get(f"/slack/connect/done?state={connect_state(install, 'U9')}")
    assert r.status_code in (302, 401, 403)
    assert SlackIdentity.objects.count() == 0


def test_connect_callback_never_falls_back_to_email(client_local, install, member, other_org_member):
    """Regression guard for the email-fallback ban. If a wrong implementation
    ever looked the Slack user up by an email claim instead of trusting only
    who is logged in, this would create an identity for other_org_member even
    though the state names `member`'s account -- it must not."""
    r = client_local.get(f"/slack/connect/done?state={connect_state(install, 'U9')}")
    assert r.status_code == 200
    identity = SlackIdentity.objects.get(install=install, slack_user_id="U9")
    assert identity.member == member
    assert identity.member != other_org_member


# --- connect begin: preserves state through the login hop ---


def test_connect_begin_sends_an_anonymous_visitor_through_login(client, install):
    r = client.get(f"/slack/connect?state={connect_state(install, 'U9')}")
    assert r.status_code == 302
    assert r["Location"].startswith("/login/")
    assert "next=" in r["Location"]
    assert "slack%2Fconnect%2Fdone" in r["Location"] or "/slack/connect/done" in r["Location"]


def test_connect_begin_skips_login_for_an_already_authenticated_visitor(client_local, install):
    r = client_local.get(f"/slack/connect?state={connect_state(install, 'U9')}")
    assert r.status_code == 302
    assert r["Location"].startswith("/slack/connect/done")


# --- slash command: same signature verification as slack_events ---


def test_command_requires_a_valid_signature(client):
    """A signature-less POST to /slack/command must be refused. Without this,
    anyone could hit the endpoint directly and get tuckit to hand back a
    connect link for an arbitrary team_id/user_id pair."""
    r = client.post(
        "/slack/command", data={"team_id": "T1", "user_id": "U9", "text": "connect"},
    )
    assert r.status_code == 401


def test_command_rejects_a_forged_signature(client, install):
    raw, ts, _ = _signed_command({"team_id": "T1", "user_id": "U9", "text": "connect"})
    bad_sig = "v0=" + hmac.new(b"wrong-secret", b"v0:" + ts.encode() + b":" + raw, hashlib.sha256).hexdigest()
    r = client.post(
        "/slack/command", data=raw, content_type="application/x-www-form-urlencoded",
        HTTP_X_SLACK_REQUEST_TIMESTAMP=ts, HTTP_X_SLACK_SIGNATURE=bad_sig,
    )
    assert r.status_code == 401


def test_command_connect_replies_with_the_connect_button(client, install):
    raw, ts, sig = _signed_command({"team_id": "T1", "user_id": "U9", "text": "connect"})
    r = client.post(
        "/slack/command", data=raw, content_type="application/x-www-form-urlencoded",
        HTTP_X_SLACK_REQUEST_TIMESTAMP=ts, HTTP_X_SLACK_SIGNATURE=sig,
    )
    assert r.status_code == 200
    body = json.loads(r.content)
    assert body["response_type"] == "ephemeral"
    assert "connect" in json.dumps(body["blocks"]).lower()


def test_command_unknown_subcommand_names_the_only_one_that_exists(client, install):
    raw, ts, sig = _signed_command({"team_id": "T1", "user_id": "U9", "text": "frobnicate"})
    r = client.post(
        "/slack/command", data=raw, content_type="application/x-www-form-urlencoded",
        HTTP_X_SLACK_REQUEST_TIMESTAMP=ts, HTTP_X_SLACK_SIGNATURE=sig,
    )
    assert r.status_code == 200
    body = json.loads(r.content)
    assert "connect" in body["text"].lower()


def test_command_unknown_team_gets_a_plain_message_not_a_broken_link(client):
    raw, ts, sig = _signed_command({"team_id": "T-NOPE", "user_id": "U9", "text": "connect"})
    r = client.post(
        "/slack/command", data=raw, content_type="application/x-www-form-urlencoded",
        HTTP_X_SLACK_REQUEST_TIMESTAMP=ts, HTTP_X_SLACK_SIGNATURE=sig,
    )
    assert r.status_code == 200
    body = json.loads(r.content)
    assert "not connected" in body["text"].lower()
