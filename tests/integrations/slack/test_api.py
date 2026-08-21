import httpx
import pytest

from tuckit.integrations.slack.api import SlackApiError, SlackClient


def client_with(handler) -> SlackClient:
    c = SlackClient("xoxb-test")
    c._http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://slack.com/api")
    return c


def test_post_message_returns_the_ts():
    def handler(request):
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
