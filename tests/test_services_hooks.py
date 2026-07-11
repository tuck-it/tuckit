import pytest
from django.test import override_settings

from tuckit.core.services.hooks import run_signup_hook

_calls = []


def _record_hook(*, user, org):
    _calls.append((user, org))


@override_settings(TUCKIT_SIGNUP_HOOK="tests.test_services_hooks._record_hook")
def test_run_signup_hook_calls_configured_hook():
    _calls.clear()
    run_signup_hook(user="u", org="o")
    assert _calls == [("u", "o")]


@override_settings(TUCKIT_SIGNUP_HOOK=None)
def test_run_signup_hook_noop_when_unset():
    _calls.clear()
    run_signup_hook(user="u", org="o")
    assert _calls == []
