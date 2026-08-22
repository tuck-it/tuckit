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
