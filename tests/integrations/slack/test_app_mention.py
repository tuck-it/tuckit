# tests/integrations/slack/test_app_mention.py
import pytest

from tuckit.core.models import Slice
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
    assert Slice.objects.get(title="The bug").area is None


def test_over_the_cap_writes_nothing_and_says_so(install, member, fake_slack, monkeypatch):
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)

    def boom(**kw):
        raise TooManyIntents("6 intents exceeds the cap of 5")

    monkeypatch.setattr("tuckit.integrations.slack.handlers.interpret", boom)
    handle_app_mention(team_id="T1", event=EVENT)
    assert Slice.objects.count() == 0
    assert len(fake_slack.updated) == 1


def test_a_model_failure_replaces_the_placeholder_rather_than_going_silent(
    install, member, fake_slack, monkeypatch,
):
    SlackIdentity.objects.create(install=install, slack_user_id="U9", member=member)

    def boom(**kw):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr("tuckit.integrations.slack.handlers.interpret", boom)
    handle_app_mention(team_id="T1", event=EVENT)
    assert len(fake_slack.updated) == 1
    assert Slice.objects.count() == 0


def test_an_unknown_team_is_ignored(fake_slack):
    handle_app_mention(team_id="T-nope", event=EVENT)
    assert not fake_slack.posted and not fake_slack.ephemeral
