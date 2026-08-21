import pytest
from django.db import IntegrityError

from tuckit.integrations.slack.models import SlackEvent, SlackIdentity, SlackInstall

pytestmark = pytest.mark.django_db


def test_one_team_maps_to_one_org(org, org_factory):
    other = org_factory()
    SlackInstall.objects.create(org=org, team_id="T1", bot_token="x", bot_user_id="U0")
    with pytest.raises(IntegrityError):
        SlackInstall.objects.create(org=other, team_id="T1", bot_token="y", bot_user_id="U0")


def test_event_id_is_unique(db):
    SlackEvent.objects.create(event_id="Ev1")
    with pytest.raises(IntegrityError):
        SlackEvent.objects.create(event_id="Ev1")


def test_a_slack_user_maps_once_per_install(org, member_factory):
    install = SlackInstall.objects.create(org=org, team_id="T2", bot_token="x", bot_user_id="U0")
    first, second = member_factory(), member_factory()
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=first)
    with pytest.raises(IntegrityError):
        SlackIdentity.objects.create(install=install, slack_user_id="U9", member=second)


def test_an_ended_membership_still_resolves_through_the_fk(org, member):
    """Attribution outlives the membership, and that is deliberate.

    This is the reason the FK cannot be the access gate: base_manager_name is
    all_objects, so the row is still reachable here. The gate is the filter in
    resolve_member, tested in the identity bite.
    """
    from django.utils import timezone

    install = SlackInstall.objects.create(org=org, team_id="T3", bot_token="x", bot_user_id="U0")
    identity = SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)

    member.ended_at = timezone.now()
    member.save(update_fields=["ended_at"])

    identity.refresh_from_db()
    assert identity.member.id == member.id  # FK resolves the ended membership
    assert identity.member.ended_at is not None  # it is indeed ended
