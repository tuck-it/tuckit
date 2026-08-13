import logging

import pytest

from tuckit.core.models import Org, ThrottleEpisode
from tuckit.core.mcp.auth import Connection
from tuckit.core.services import ratelimit, throttle
from tuckit.core.services.exceptions import LimitReached


@pytest.fixture(autouse=True)
def clean_state():
    ratelimit.reset()
    throttle.reset()
    yield
    ratelimit.reset()
    throttle.reset()


@pytest.fixture
def conn(db):
    org = Org.objects.create(name="Acme", slug="acme")
    return Connection(
        org=org, user=None, key=("oauth", 1, 1, org.id),
        label="Claude Code · a@b.co",
    )


@pytest.fixture
def tight(settings):
    settings.TUCKIT_MCP_RATE_CONN_BURST = 1.0
    settings.TUCKIT_MCP_RATE_CONN_PER_SEC = 1.0
    settings.TUCKIT_MCP_RATE_ORG_PER_SEC = 0.0
    return settings


def test_a_refusal_writes_one_episode_naming_the_connection(conn, tight):
    throttle.check(conn)
    with pytest.raises(LimitReached):
        throttle.check(conn)
    episodes = list(ThrottleEpisode.objects.all())
    assert len(episodes) == 1
    assert episodes[0].org_id == conn.org.id
    assert episodes[0].label == "Claude Code · a@b.co"


def test_a_hundred_refusals_inside_the_window_write_exactly_one_row(conn, tight):
    """Without suppression the defence becomes the load it exists to prevent."""
    throttle.check(conn)
    for _ in range(100):
        with pytest.raises(LimitReached):
            throttle.check(conn)
    assert ThrottleEpisode.objects.count() == 1


def test_a_new_episode_is_written_after_the_window(conn, tight):
    throttle.check(conn)
    with pytest.raises(LimitReached):
        throttle.check(conn)
    # Move the recorded time back past the window without moving the bucket.
    throttle._last_recorded[conn.key] -= throttle.EPISODE_SUPPRESS_SECONDS + 1
    with pytest.raises(LimitReached):
        throttle.check(conn)
    assert ThrottleEpisode.objects.count() == 2


def test_passing_calls_write_nothing(conn, settings):
    settings.TUCKIT_MCP_RATE_CONN_BURST = 100.0
    settings.TUCKIT_MCP_RATE_CONN_PER_SEC = 10.0
    settings.TUCKIT_MCP_RATE_ORG_PER_SEC = 0.0
    for _ in range(50):
        throttle.check(conn)
    assert ThrottleEpisode.objects.count() == 0


def test_the_org_backstop_writes_no_row_and_logs_instead(conn, settings, caplog):
    settings.TUCKIT_MCP_RATE_CONN_PER_SEC = 0.0
    settings.TUCKIT_MCP_RATE_ORG_BURST = 1.0
    settings.TUCKIT_MCP_RATE_ORG_PER_SEC = 1.0
    throttle.check(conn)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(LimitReached):
            throttle.check(conn)
    assert ThrottleEpisode.objects.count() == 0
    assert "org rate limit" in caplog.text
    assert "acme" in caplog.text
