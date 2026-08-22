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


def event_for(url: str) -> dict:
    return {"type": "link_shared", "channel": "C1", "user": "U9", "message_ts": "1.0",
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
    """What Slack sends while the link is still in the composer.

    No message exists yet, so there is no message_ts to attach an unfurl to.
    Slack sends this in ADDITION to the conversations_history event that
    follows once the message is posted, so a paste produces two events.
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
    """The real event lands milliseconds later and must still be answered.

    This is the half that made the defect invisible: the composer call
    'succeeded', so the cooldown row was written, and the posted-message event
    that followed was skipped as a repeat. One paste, no card, and the ref
    unexpandable for an hour.
    """
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    slice_ = slice_factory()
    url = f"https://x/?slice={slice_.id}"

    handle_link_shared(team_id="T1", event=composer_event_for(url))
    assert SlackUnfurl.objects.count() == 0

    handle_link_shared(team_id="T1", event=event_for(url))
    assert len(fake_slack.unfurled) == 1
    assert fake_slack.unfurled[0]["ts"] == "1.0"
