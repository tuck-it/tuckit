# tests/integrations/slack/test_app_mention.py
import pytest

from tests.integrations.slack.test_cards import text_of
from tuckit.core.models import Slice
from tuckit.core.services.refs import slice_ref
from tuckit.integrations.slack.handlers import handle_app_mention
from tuckit.integrations.slack.interpret import Intent, TooManyIntents
from tuckit.integrations.slack.models import SlackIdentity, SlackInstall

pytestmark = pytest.mark.django_db

# FakeSlack and the fake_slack fixture come from tests/integrations/slack/conftest.py
# (shared by every handler test, per bite 252) rather than a local copy here --
# a local copy would silently drift from the shared one as later bites (e.g. 249's
# chat_unfurl/unfurled) extend it.


@pytest.fixture
def install(org):
    return SlackInstall.objects.create(org=org, team_id="T1", bot_token="x", bot_user_id="U0")


EVENT = {"type": "app_mention", "channel": "C1", "user": "U9", "ts": "1.0", "thread_ts": "0.9",
         "text": "<@U0> file it"}


def test_unlinked_user_gets_an_ephemeral_prompt_and_no_placeholder(install, fake_slack):
    handle_app_mention(team_id="T1", event=EVENT)
    assert fake_slack.ephemeral and not fake_slack.posted
    assert Slice.objects.count() == 0


def test_linked_user_gets_a_placeholder_then_an_update(install, member, fake_slack, monkeypatch):
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)
    monkeypatch.setattr(
        "tuckit.integrations.slack.handlers.interpret",
        lambda **kw: [Intent("create_slice", {"title": "The bug", "spec": "x", "area": ""})],
    )
    handle_app_mention(team_id="T1", event=EVENT)
    assert len(fake_slack.posted) == 1
    assert len(fake_slack.updated) == 1
    assert fake_slack.updated[0]["ts"] == "ts-1"
    created = Slice.objects.get(title="The bug")
    assert created.area is None
    # The placeholder and the card that replaces it must both carry content.
    # FakeSlack.replies is two messages, so the counts are pinned too.
    assert "2 messages" in fake_slack.posted[0]["text"]
    said = text_of(fake_slack.updated[0]["blocks"])
    assert slice_ref(created) in said
    assert "The bug" in said
    assert f"/slices/{created.id}/" in said
    assert member.user.email in said


def test_over_the_cap_writes_nothing_and_says_so(install, member, fake_slack, monkeypatch):
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)

    def boom(**kw):
        raise TooManyIntents("6 intents exceeds the cap of 5")

    monkeypatch.setattr("tuckit.integrations.slack.handlers.interpret", boom)
    handle_app_mention(team_id="T1", event=EVENT)
    assert Slice.objects.count() == 0
    # `len(updated) == 1` alone passes for a card that says nothing at all,
    # which is the failure this test names. Read what the person sees.
    assert len(fake_slack.updated) == 1
    said = text_of(fake_slack.updated[0]["blocks"])
    assert "more than five separate things" in said
    assert "have not filed anything" in said


def test_a_model_failure_replaces_the_placeholder_rather_than_going_silent(
    install, member, fake_slack, monkeypatch,
):
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)

    def boom(**kw):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr("tuckit.integrations.slack.handlers.interpret", boom)
    handle_app_mention(team_id="T1", event=EVENT)
    assert Slice.objects.count() == 0
    # Same point as the cap test above: replacing the placeholder with an
    # empty card is still going silent, so assert the sentence, not the count.
    assert len(fake_slack.updated) == 1
    said = text_of(fake_slack.updated[0]["blocks"])
    assert "could not read this thread" in said
    assert "Mention me again to retry" in said


def test_an_unknown_team_is_ignored(fake_slack):
    handle_app_mention(team_id="T-nope", event=EVENT)
    assert not fake_slack.posted and not fake_slack.ephemeral
