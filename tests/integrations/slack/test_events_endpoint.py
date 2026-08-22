import hashlib
import hmac
import importlib
import json
import time

import pytest
from django.db import transaction
from django.urls import clear_url_caches

import tuckit.urls as root_urls
import tuckit.web.urls as web_urls
from tuckit.integrations.slack.models import SlackEvent

# transaction=True: the view registers work via transaction.on_commit, and
# plain @pytest.mark.django_db wraps each test in an atomic block that is
# rolled back rather than committed, so on_commit callbacks never fire. The
# repo's other tests that exercise on_commit-dependent behavior use the same
# marker (see tests/test_mcp_db_connection_lifecycle.py, tests/test_oauth_e2e.py).
pytestmark = pytest.mark.django_db(transaction=True)

SECRET = "test-signing-secret"


def _reload_urlconf():
    """Force Django to rebuild the live URLconf from the current settings.

    tuckit/web/urls.py calls slack_urlpatterns() exactly once, at import
    time, so whether /slack/events exists depends on whatever SLACK_* values
    were set the *first* time that module was imported this process -- not
    on whatever the `settings` fixture holds during this test. In the full
    suite, some unrelated earlier test resolves a URL first (with Slack
    unconfigured, the default), which is enough to permanently decide the
    route is absent for the rest of the process unless we intervene here.

    clear_url_caches() alone is not enough: URLResolver.url_patterns is a
    cached_property on the resolver instance living inside the *root*
    urlconf module (tuckit/urls.py), and that instance is only replaced when
    tuckit.urls itself is reimported. So both modules need a real reload --
    web.urls first (so its urlpatterns reflect the current settings), then
    the root urlconf (so its `include("tuckit.web.urls")` resolver gets
    rebuilt against the freshly reloaded module) -- before clearing the
    resolver cache.
    """
    importlib.reload(web_urls)
    importlib.reload(root_urls)
    clear_url_caches()


@pytest.fixture(autouse=True)
def _configured():
    # Deliberately not using the `settings` fixture here: its finalizer
    # (which reverts these three values) runs *after* this fixture's own
    # teardown -- a fixture requested as a dependency tears down last, so a
    # post-yield reload driven by that fixture would still see the
    # overridden values and rebuild the URLconf as "configured" instead of
    # restoring reality. Owning the save/restore directly keeps the exact
    # ordering in our hands.
    from django.conf import settings as dj_settings

    prev = {
        name: getattr(dj_settings, name, "")
        for name in ("SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET", "SLACK_SIGNING_SECRET")
    }
    dj_settings.SLACK_CLIENT_ID = "1.2"
    dj_settings.SLACK_CLIENT_SECRET = "s"
    dj_settings.SLACK_SIGNING_SECRET = SECRET
    _reload_urlconf()
    yield
    for name, value in prev.items():
        setattr(dj_settings, name, value)
    _reload_urlconf()


def post(client, body: dict, secret: str = SECRET):
    raw = json.dumps(body).encode()
    ts = str(int(time.time()))
    base = b"v0:" + ts.encode() + b":" + raw
    sig = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return client.post(
        "/slack/events", data=raw, content_type="application/json",
        HTTP_X_SLACK_REQUEST_TIMESTAMP=ts, HTTP_X_SLACK_SIGNATURE=sig,
    )


def test_url_verification_echoes_the_challenge(client):
    r = post(client, {"type": "url_verification", "challenge": "abc123"})
    assert r.status_code == 200
    assert r.json()["challenge"] == "abc123"


def test_a_forged_signature_is_rejected(client):
    r = post(client, {"type": "url_verification", "challenge": "x"}, secret="wrong")
    assert r.status_code == 401


def test_the_same_event_id_is_only_processed_once(client, monkeypatch):
    queued = []
    monkeypatch.setattr(
        "tuckit.integrations.slack.views.enqueue",
        lambda name, payload: queued.append(name),
    )
    body = {
        "type": "event_callback", "event_id": "Ev123", "team_id": "T1",
        "event": {"type": "app_mention", "channel": "C1", "user": "U1", "ts": "1.0"},
    }
    assert post(client, body).status_code == 200
    assert post(client, body).status_code == 200
    assert queued == ["slack.app_mention"]
    assert SlackEvent.objects.filter(event_id="Ev123").count() == 1


def test_the_job_is_queued_only_after_the_row_commits(client, monkeypatch):
    """Pins the on_commit ordering directly, without needing a real race.

    The view wraps its write in its own `transaction.atomic()`. Wrapping the
    whole request in an *outer* atomic block here turns the view's block into
    a savepoint: on_commit callbacks registered inside a savepoint are held
    until the outermost transaction actually commits, not when the savepoint
    is released. So while we are still inside the `with` below, the row has
    been written but is not durable yet, and nothing may have been queued. A
    bare `enqueue(...)` in place of `transaction.on_commit(...)` would run
    immediately and fail the first assertion.
    """
    queued = []
    monkeypatch.setattr(
        "tuckit.integrations.slack.views.enqueue",
        lambda name, payload: queued.append(name),
    )
    body = {
        "type": "event_callback", "event_id": "EvOrdering", "team_id": "T1",
        "event": {"type": "app_mention", "channel": "C1", "user": "U1", "ts": "1.0"},
    }
    with transaction.atomic():
        assert post(client, body).status_code == 200
        # Still inside the outer transaction: the row is not durable yet, so
        # the on_commit hook must not have fired.
        assert queued == []
    # The outer commit has now run the deferred on_commit hooks.
    assert queued == ["slack.app_mention"]


def test_the_enqueued_payload_carries_team_id_and_event(client, monkeypatch):
    """Guards the exact payload shape the bite body specifies.

    A test that only checked `queued == ["slack.app_mention"]` would still
    pass for an implementation that enqueued the wrong payload (e.g. the
    whole top-level `payload` dict instead of `{"team_id": ..., "event":
    ...}`), which would break every downstream handler that expects
    keyword-unpackable `team_id` and `event` arguments.
    """
    calls = []
    monkeypatch.setattr(
        "tuckit.integrations.slack.views.enqueue",
        lambda name, payload: calls.append((name, payload)),
    )
    event = {"type": "app_mention", "channel": "C1", "user": "U1", "ts": "1.0"}
    body = {"type": "event_callback", "event_id": "Ev999", "team_id": "T9", "event": event}
    assert post(client, body).status_code == 200
    assert calls == [("slack.app_mention", {"team_id": "T9", "event": event})]


def test_an_unrecognised_event_type_is_acked_and_not_queued(client, monkeypatch):
    """An event type we don't handle must still get a 200 (Slack must never
    be left retrying something we will never process), and must not enqueue
    anything or create a ledger row -- a wrong implementation could satisfy
    "acked" while still queuing a bogus job or growing the SlackEvent table
    forever for noise events."""
    queued = []
    monkeypatch.setattr(
        "tuckit.integrations.slack.views.enqueue",
        lambda name, payload: queued.append(name),
    )
    body = {
        "type": "event_callback", "event_id": "EvUnknown", "team_id": "T1",
        "event": {"type": "reaction_added", "user": "U1"},
    }
    r = post(client, body)
    assert r.status_code == 200
    assert queued == []
    assert not SlackEvent.objects.filter(event_id="EvUnknown").exists()


def test_a_failed_enqueue_gives_the_idempotency_token_back(monkeypatch):
    """A burned token loses the event forever, so it must not be burned.

    The SlackEvent row is written and committed before enqueue runs. If
    enqueue then fails (Cloud Tasks 503, IAM gap, misconfigured queue) and the
    row survives, Slack's retry of the same event_id finds it, takes the
    IntegrityError branch, answers 200 and queues nothing: no job, no
    placeholder, no reply, and no further retry coming. The row that exists to
    make Slack's retry safe would be the thing that defeated it.

    A separate Client with raise_request_exception=False is needed because the
    on_commit hook re-raises: the view really does 500, and the default test
    client would surface that as a raised exception instead of a response.
    """
    from django.test import Client as DjangoClient

    calls = []

    def flaky(name, payload):
        calls.append(name)
        if len(calls) == 1:
            raise RuntimeError("Cloud Tasks refused the task")

    monkeypatch.setattr("tuckit.integrations.slack.views.enqueue", flaky)
    body = {
        "type": "event_callback", "event_id": "EvBurned", "team_id": "T1",
        "event": {"type": "app_mention", "channel": "C1", "user": "U1", "ts": "1.0"},
    }
    failing_client = DjangoClient(raise_request_exception=False)

    # First delivery: enqueue fails, so Slack must be told to retry (5xx) and
    # the row must not be left behind.
    first = post(failing_client, body)
    assert first.status_code == 500
    assert not SlackEvent.objects.filter(event_id="EvBurned").exists()

    # Slack's retry of the SAME event_id must now be allowed to do the work.
    second = post(failing_client, body)
    assert second.status_code == 200
    assert calls == ["slack.app_mention", "slack.app_mention"]
    assert SlackEvent.objects.filter(event_id="EvBurned").count() == 1


def test_endpoint_is_absent_when_not_configured(client, settings):
    settings.SLACK_SIGNING_SECRET = ""
    settings.SLACK_CLIENT_ID = ""
    settings.SLACK_CLIENT_SECRET = ""
    # The URLconf is built at import time, so assert directly against the
    # builder function rather than relying on a live reload of web.urls.
    from tuckit.integrations.slack.urls import slack_urlpatterns

    assert slack_urlpatterns() == []


def test_the_settings_routes_are_absent_when_not_configured(settings):
    """Resolved through the LIVE URLconf, not the builder function.

    The org-scoped Slack settings routes were mounted unconditionally while
    the org-less ones were gated, so an unconfigured deployment still served
    /<org>/settings/slack with a working "Connect to Slack" button, and
    slack_install_begin raised NoReverseMatch (a 500) for any admin who
    reached it. The nav link is hidden in that state, which is why nothing
    caught it.

    Asserting against slack_settings_urlpatterns() alone would not catch the
    regression that matters: web/urls.py could stop calling the builder and
    re-list the four paths itself, and a builder-only test would stay green.
    So this resolves real paths and reverses real names.
    """
    from django.urls import NoReverseMatch, Resolver404, resolve, reverse

    # Configured (the autouse fixture's state): all four exist.
    assert resolve("/acme/settings/slack").view_name == "web:settings_slack"
    for name in ("settings_slack", "slack_install_begin",
                 "slack_install_confirm", "slack_disconnect"):
        assert reverse(f"web:{name}", kwargs={"org_slug": "acme"})

    settings.SLACK_SIGNING_SECRET = ""
    settings.SLACK_CLIENT_ID = ""
    settings.SLACK_CLIENT_SECRET = ""
    _reload_urlconf()
    # The autouse _configured fixture restores the real settings and reloads
    # the URLconf on teardown, so nothing needs unwinding here.
    for path_ in ("/acme/settings/slack", "/acme/settings/slack/connect",
                  "/acme/settings/slack/confirm", "/acme/settings/slack/disconnect"):
        with pytest.raises(Resolver404):
            resolve(path_)
    for name in ("settings_slack", "slack_install_begin",
                 "slack_install_confirm", "slack_disconnect"):
        with pytest.raises(NoReverseMatch):
            reverse(f"web:{name}", kwargs={"org_slug": "acme"})
