import pytest
from django.utils import timezone

from tuckit.core.models import CanvasWatch
from tuckit.core.services.slices import create_slice
from tuckit.core.services.watches import (
    ANSWER_GRACE, WATCH_TTL, answer_watches, close_watches, open_watch, read_watch,
)


@pytest.mark.django_db
def test_a_fresh_watch_is_waiting(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")

    _, raw = open_watch(s)

    assert read_watch(raw) == {"status": "waiting"}


@pytest.mark.django_db
def test_the_raw_token_is_never_stored(org, area):
    """Whoever holds the URL holds the capability, so a leaked row must not be
    usable -- the same rule OAuthAccessToken follows."""
    s = create_slice(org, area=area, title="Canvas", spec="")

    watch, raw = open_watch(s)

    assert raw not in watch.token_hash
    assert len(watch.token_hash) == 64
    assert len(raw) >= 32


@pytest.mark.django_db
def test_an_answer_is_readable_more_than_once(org, area):
    """A poll loop retries. A token that died on its first read would strand an
    agent whose one request happened to fail."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    _, raw = open_watch(s)

    answer_watches(s, "o2")

    assert read_watch(raw) == {"status": "chosen", "choice": "o2"}
    assert read_watch(raw) == {"status": "chosen", "choice": "o2"}


@pytest.mark.django_db
def test_answering_shortens_the_life_to_the_grace_window(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    watch, _ = open_watch(s)
    assert watch.expires_at > timezone.now() + ANSWER_GRACE   # not already short

    answer_watches(s, "o2")

    watch.refresh_from_db()
    assert watch.expires_at <= timezone.now() + ANSWER_GRACE
    assert watch.expires_at > timezone.now()                  # still deliverable


@pytest.mark.django_db
def test_an_already_answered_watch_keeps_its_first_answer(org, area):
    """The second click is a different question's answer, or a correction on a
    channel whose reader has already moved on. Either way it does not rewrite
    an answer somebody may have acted on."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    _, raw = open_watch(s)

    answer_watches(s, "o1")
    answer_watches(s, "o2")

    assert read_watch(raw) == {"status": "chosen", "choice": "o1"}


@pytest.mark.django_db
def test_an_expired_watch_is_simply_gone(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    watch, raw = open_watch(s)
    watch.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    watch.save(update_fields=["expires_at"])

    assert read_watch(raw) is None


@pytest.mark.django_db
def test_an_unknown_token_reads_the_same_as_an_expired_one(org, area):
    assert read_watch("not-a-token") is None


@pytest.mark.django_db
def test_closing_retires_every_watch_on_the_slice(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    _, one = open_watch(s)
    _, two = open_watch(s)

    close_watches(s)

    assert read_watch(one) is None and read_watch(two) is None


@pytest.mark.django_db
def test_the_ttl_is_the_advertised_fifteen_minutes(org, area):
    """The skill's poll loop is sized against this number (450 x 2s). If the
    constant moves, that loop has to move with it."""
    assert WATCH_TTL == timezone.timedelta(minutes=15)


@pytest.mark.django_db
def test_opening_sweeps_the_org_s_dead_watches(org, area):
    """No cron: the write path pays for its own cleanup."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    dead, _ = open_watch(s)
    dead.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    dead.save(update_fields=["expires_at"])

    open_watch(s)

    assert not CanvasWatch.objects.filter(pk=dead.pk).exists()
