import json

import httpx
import pytest

from tuckit.integrations.slack.api import SlackApiError, SlackClient


def client_with(handler) -> SlackClient:
    c = SlackClient("xoxb-test")
    c._http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://slack.com/api")
    return c


def test_post_message_returns_the_ts():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path.endswith("/chat.postMessage")
        assert request.headers["authorization"] == "Bearer xoxb-test"
        return httpx.Response(200, json={"ok": True, "ts": "1700000000.000100"})

    assert client_with(handler).post_message(channel="C1", text="hi") == "1700000000.000100"


def test_an_ok_false_body_raises_even_though_http_is_200():
    def handler(request):
        return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})

    with pytest.raises(SlackApiError, match="channel_not_found"):
        client_with(handler).post_message(channel="C1", text="hi")


def test_conversations_replies_returns_messages():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "messages": [{"text": "a"}, {"text": "b"}]})

    msgs = client_with(handler).conversations_replies(channel="C1", thread_ts="1.0")
    assert [m["text"] for m in msgs] == ["a", "b"]


def test_exchange_oauth_code_raises_on_ok_false(settings, monkeypatch):
    settings.SLACK_CLIENT_ID = "test-id"
    settings.SLACK_CLIENT_SECRET = "test-secret"

    def mock_post(*args, **kwargs):
        resp = httpx.Response(200, json={"ok": False, "error": "invalid_code"})
        resp._request = httpx.Request("POST", "https://slack.com/api/oauth.v2.access")
        return resp

    import tuckit.integrations.slack.api
    monkeypatch.setattr(tuckit.integrations.slack.api.httpx, "post", mock_post)

    with pytest.raises(SlackApiError, match="invalid_code"):
        from tuckit.integrations.slack.api import exchange_oauth_code
        exchange_oauth_code(code="test-code", redirect_uri="https://example.com/callback")


def test_chat_unfurl_sends_the_map_as_a_json_string_not_an_object():
    """Slack types `unfurls` as a string: "URL-encoded JSON map with keys set
    to URLs featured in the message", unlike every other argument we send.

    This pins conformance to the documented type. It is NOT a regression test:
    the live API accepts a bare object over a JSON body too, verified against a
    real workspace. Send the documented shape so a future tightening cannot
    reach us, and do not cite this test as evidence that the object form is
    broken.
    """
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    card = {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "*TP-1*"}}]}
    client_with(handler).chat_unfurl(
        channel="C1", ts="1.0", unfurls={"https://app.tuckit.dev/?slice=1": card},
    )

    assert isinstance(seen["unfurls"], str), "sent as an object; Slack will silently draw nothing"
    assert json.loads(seen["unfurls"]) == {"https://app.tuckit.dev/?slice=1": card}
