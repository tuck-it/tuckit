"""Bite 249: unfurl tuckit links, permission-checked and rate-limited.

Two rules under test, both about not leaking:
1. Unfurling requires the person who pasted the link to resolve to a member
   of the org that owns the ref -- an unresolvable person, or a ref from
   another org, must produce no unfurl at all (never an error, which would
   itself confirm the ref exists).
2. The same ref must not be re-expanded within 60 minutes.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from tuckit.integrations.slack.api import SlackApiError
from tuckit.integrations.slack.handlers import handle_link_shared
from tuckit.integrations.slack.models import SlackIdentity, SlackInstall, SlackUnfurl

pytestmark = pytest.mark.django_db


@pytest.fixture
def install(org):
    return SlackInstall.objects.create(org=org, team_id="T1", bot_token="x", bot_user_id="U0")


def event_for(url: str, channel: str = "C1") -> dict:
    """One link_shared. `channel` is a parameter because the cooldown is keyed
    on it -- a helper that hard-codes one channel cannot see a cooldown that
    leaks across channels, which is precisely the defect this file missed.
    """
    return {"type": "link_shared", "channel": channel, "user": "U9", "message_ts": "1.0",
            "links": [{"url": url, "domain": "app.tuckit.dev"}]}


def test_a_member_gets_the_unfurl(install, member, slice_factory, fake_slack, settings):
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    target = slice_factory(title="Visible")
    url = f"{settings.TUCKIT_BASE_URL}/{install.org.slug}/?slice={target.id}"
    handle_link_shared(team_id="T1", event=event_for(url))
    assert fake_slack.unfurled and "Visible" in str(fake_slack.unfurled[0])


def test_an_unlinked_person_gets_nothing_at_all(install, slice_factory, fake_slack, settings):
    target = slice_factory(title="Secret")
    url = f"{settings.TUCKIT_BASE_URL}/{install.org.slug}/?slice={target.id}"
    handle_link_shared(team_id="T1", event=event_for(url))
    assert fake_slack.unfurled == []


def test_a_ref_from_another_org_is_not_expanded(install, member, other_org_slice, fake_slack, settings):
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    url = f"{settings.TUCKIT_BASE_URL}/{other_org_slice.org.slug}/?slice={other_org_slice.id}"
    handle_link_shared(team_id="T1", event=event_for(url))
    assert fake_slack.unfurled == []


def test_the_same_ref_is_not_expanded_twice_within_the_hour(
    install, member, slice_factory, fake_slack, settings,
):
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    target = slice_factory(title="Repeated")
    url = f"{settings.TUCKIT_BASE_URL}/{install.org.slug}/?slice={target.id}"
    handle_link_shared(team_id="T1", event=event_for(url))
    handle_link_shared(team_id="T1", event=event_for(url))
    assert len(fake_slack.unfurled) == 1


def test_the_same_ref_in_another_channel_is_still_expanded(
    install, member, slice_factory, fake_slack, settings,
):
    """The cooldown stops a channel from redrawing the same card, not a
    workspace from ever seeing it twice.

    Alice shares a ref in #eng; ten minutes later Bob shares it in #design.
    Bob's channel must get a card. Keyed on (install, ref) alone, Bob sees
    nothing at all -- and unfurling is the one path that is forbidden to
    explain itself, so nothing is logged and nobody can tell why.
    """
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    target = slice_factory(title="Shared twice")
    url = f"{settings.TUCKIT_BASE_URL}/{install.org.slug}/?slice={target.id}"

    handle_link_shared(team_id="T1", event=event_for(url, channel="C-eng"))
    handle_link_shared(team_id="T1", event=event_for(url, channel="C-design"))

    assert len(fake_slack.unfurled) == 2
    assert [u["channel"] for u in fake_slack.unfurled] == ["C-eng", "C-design"]


def test_the_cooldown_is_recorded_against_the_channel_it_was_drawn_in(
    install, member, slice_factory, fake_slack, settings,
):
    """A second card in the same channel is still suppressed."""
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    target = slice_factory(title="Repeated in one channel")
    url = f"{settings.TUCKIT_BASE_URL}/{install.org.slug}/?slice={target.id}"

    handle_link_shared(team_id="T1", event=event_for(url, channel="C-eng"))
    handle_link_shared(team_id="T1", event=event_for(url, channel="C-eng"))

    assert len(fake_slack.unfurled) == 1
    assert SlackUnfurl.objects.filter(install=install, channel="C-eng").count() == 1


def test_the_ref_is_expanded_again_after_the_cooldown_expires(
    install, member, slice_factory, fake_slack, settings,
):
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    target = slice_factory(title="Stale")
    url = f"{settings.TUCKIT_BASE_URL}/{install.org.slug}/?slice={target.id}"
    handle_link_shared(team_id="T1", event=event_for(url))
    SlackUnfurl.objects.filter(install=install).update(
        last_unfurled_at=timezone.now() - timedelta(minutes=61),
    )
    handle_link_shared(team_id="T1", event=event_for(url))
    assert len(fake_slack.unfurled) == 2


def test_a_failed_chat_unfurl_call_does_not_propagate(
    install, member, slice_factory, fake_slack, settings, monkeypatch,
):
    """chat.unfurl can fail (SlackApiError from `_call`) after a permitted,
    non-cooldown ref has already been decided eligible. That failure must be
    swallowed, not raised: this is the one path in the integration where
    speaking at all -- even a log with the ref in it -- would confirm to
    whoever is asking that something exists. This test pins that the handler
    returns cleanly rather than letting the daemon thread running it crash.
    """
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    target = slice_factory(title="Whatever")
    url = f"{settings.TUCKIT_BASE_URL}/{install.org.slug}/?slice={target.id}"

    def boom(**kwargs):
        raise SlackApiError("chat.unfurl: some_slack_error")

    monkeypatch.setattr(fake_slack, "chat_unfurl", boom)

    handle_link_shared(team_id="T1", event=event_for(url))  # must not raise


def test_a_failed_unfurl_does_not_start_the_cooldown(
    install, member, slice_factory, fake_slack, settings, monkeypatch,
):
    """The cooldown row records that a card was drawn, so a call that drew
    nothing must not write one.

    Recording it before chat.unfurl was attempted meant one Slack hiccup
    suppressed that ref for the next 60 minutes: every later paste of the
    same link produced silence, and silence is indistinguishable here from
    "you are not allowed to see it".
    """
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    target = slice_factory(title="Retryable")
    url = f"{settings.TUCKIT_BASE_URL}/{install.org.slug}/?slice={target.id}"

    def boom(**kwargs):
        raise SlackApiError("chat.unfurl: ratelimited")

    working = fake_slack.chat_unfurl
    monkeypatch.setattr(fake_slack, "chat_unfurl", boom)
    handle_link_shared(team_id="T1", event=event_for(url))
    assert SlackUnfurl.objects.filter(install=install).count() == 0

    # The next paste of the same link gets another attempt, not an hour of
    # silence for a card nobody ever saw. Restoring the one method rather
    # than monkeypatch.undo(): undo() would also revert the fake_slack
    # fixture's own patch and send the next call at the real Slack API.
    monkeypatch.setattr(fake_slack, "chat_unfurl", working)
    handle_link_shared(team_id="T1", event=event_for(url))
    assert len(fake_slack.unfurled) == 1
    assert SlackUnfurl.objects.filter(install=install).count() == 1


def test_a_successful_unfurl_records_the_cooldown(
    install, member, slice_factory, fake_slack, settings,
):
    """The other half of the pair above: moving the write after the call must
    not lose it, or the 60-minute rule stops existing."""
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    target = slice_factory(title="Recorded")
    url = f"{settings.TUCKIT_BASE_URL}/{install.org.slug}/?slice={target.id}"
    handle_link_shared(team_id="T1", event=event_for(url))
    assert SlackUnfurl.objects.filter(install=install).count() == 1


def composer_event_for(url: str) -> dict:
    """A link_shared with no message to attach to.

    Named for the composer because that is the documented source that has no
    ts yet. We have NOT observed Slack sending one -- the handler's skip log
    has never fired in production -- so treat this as the shape of a guard,
    not as a recording of real traffic.
    """
    return {"type": "link_shared", "channel": "C1", "user": "U9", "source": "composer",
            "unfurl_id": "C1.123.abc",
            "links": [{"url": url, "domain": "app.tuckit.dev"}]}


def test_a_composer_preview_is_not_answered_at_all(
    install, member, slice_factory, fake_slack, settings,
):
    """Answering it with ts="" is accepted by Slack and draws nothing."""
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    slice_ = slice_factory()
    handle_link_shared(team_id="T1", event=composer_event_for(f"https://x/?slice={slice_.id}"))
    assert not fake_slack.unfurled


def test_a_composer_preview_does_not_burn_the_cooldown(
    install, member, slice_factory, fake_slack, settings,
):
    """A call that cannot land must not cost the ref its hour.

    chat.unfurl with an empty ts returns ok:true, so without the guard the
    cooldown row is written for an unfurl nobody ever saw, and every later
    attempt at that ref is skipped as a repeat for the next hour.
    """
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    slice_ = slice_factory()
    url = f"https://x/?slice={slice_.id}"

    handle_link_shared(team_id="T1", event=composer_event_for(url))
    assert SlackUnfurl.objects.count() == 0

    handle_link_shared(team_id="T1", event=event_for(url))
    assert len(fake_slack.unfurled) == 1
    assert fake_slack.unfurled[0]["ts"] == "1.0"
