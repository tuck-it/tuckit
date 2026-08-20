"""The deployment's notice has to reach a screen, or it does not exist.

Core supplies no wording here — these tests stand in for a deployment by
configuring a hook, then check the two places a person actually looks: the
shell they are already on, and Settings, where they go when they want to deal
with it.
"""
import pytest
from django.test import override_settings

from tuckit.core.entitlements import Entitlements


def _warn(org):
    return Entitlements(
        notice="Three days left.",
        notice_tone="warn",
        action_url="https://example.test/upgrade",
        action_label="Subscribe",
    )


def _blocked(org):
    return Entitlements(
        writes_blocked_reason="Read-only.",
        notice="This workspace is read-only.",
        notice_tone="block",
        action_url="https://example.test/upgrade",
        action_label="Subscribe",
    )


def _action_only(org):
    return Entitlements(
        action_url="https://example.test/upgrade",
        action_label="Manage subscription",
    )


WARN = override_settings(TUCKIT_ENTITLEMENTS_HOOK="tests.web.test_entitlement_notice._warn")
BLOCKED = override_settings(TUCKIT_ENTITLEMENTS_HOOK="tests.web.test_entitlement_notice._blocked")
ACTION_ONLY = override_settings(
    TUCKIT_ENTITLEMENTS_HOOK="tests.web.test_entitlement_notice._action_only"
)


# ------------------------------------------------------------------ the shell

@WARN
def test_the_notice_and_its_link_are_on_the_screen_you_are_already_looking_at(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert "Three days left." in body
    assert 'href="https://example.test/upgrade"' in body
    assert ">Subscribe</a>" in body


@WARN
def test_the_board_carries_it_too(client_local, org):
    """The Board is a fixed-height flex column; a banner that only renders on
    Home is a warning somebody can work all week without meeting."""
    assert "Three days left." in client_local.get(f"/{org.slug}/roadmap/").content.decode()


@BLOCKED
def test_a_block_is_toned_differently_from_a_warning(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert "ent-banner--block" in body


@WARN
def test_a_warning_is_not_toned_as_a_block(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert "ent-banner--warn" in body
    assert "ent-banner--block" not in body


@ACTION_ONLY
def test_an_action_with_no_notice_interrupts_nobody(client_local, org):
    """A deployment can offer the link without putting a banner on every
    screen — that is the difference between offering and interrupting."""
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert "ent-banner" not in body


@pytest.mark.django_db
def test_a_self_host_renders_none_of_it(client_local, org):
    """No hook configured is the core's own default, and it must be silent."""
    resp = client_local.get(f"/{org.slug}/")
    assert resp.status_code == 200, "not the shell, so 'no banner' proves nothing"
    body = resp.content.decode()
    assert "ent-banner" not in body


# ---------------------------------------------------------------- in settings

@ACTION_ONLY
def test_settings_offers_the_deployments_action(client_local, org):
    body = client_local.get(f"/{org.slug}/settings/general").content.decode()
    assert 'href="https://example.test/upgrade"' in body
    assert "Manage subscription" in body


@pytest.mark.django_db
def test_settings_shows_nothing_when_the_deployment_configured_nothing(client_local, org):
    resp = client_local.get(f"/{org.slug}/settings/general")
    assert resp.status_code == 200, "not the settings page, so 'no link' proves nothing"
    body = resp.content.decode()
    assert "example.test" not in body
    assert "Export" in body, "the nav rendered, so a missing entry is a real absence"
