from tuckit.integrations.slack.config import interpretation_is_configured, slack_is_configured


def test_not_configured_by_default(settings):
    settings.SLACK_CLIENT_ID = ""
    settings.SLACK_CLIENT_SECRET = ""
    settings.SLACK_SIGNING_SECRET = ""
    assert slack_is_configured() is False


def test_needs_all_three(settings):
    settings.SLACK_CLIENT_ID = "123.456"
    settings.SLACK_CLIENT_SECRET = "s"
    settings.SLACK_SIGNING_SECRET = ""
    assert slack_is_configured() is False
    settings.SLACK_SIGNING_SECRET = "sign"
    assert slack_is_configured() is True


def test_interpretation_is_a_separate_switch(settings):
    settings.ANTHROPIC_API_KEY = ""
    assert interpretation_is_configured() is False
    settings.ANTHROPIC_API_KEY = "sk-ant-x"
    assert interpretation_is_configured() is True
