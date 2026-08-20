"""Pressing Invite has to tell you whether anybody was told.

The row said "Invited" and meant only that a row existed. Whether the email
went was unknowable from the screen — and, with fail_silently, unknowable from
the logs too.
"""
import json

import pytest
from django.core import mail
from django.test import override_settings

NO_MAIL = override_settings(
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST="",
    DEFAULT_FROM_EMAIL="",
)


def _invite(client, org, email="new@x.com"):
    return client.post(f"/{org.slug}/settings/invites", {"email": email, "role": "member"})


@pytest.mark.django_db
def test_a_sent_invitation_says_so(client_local, org):
    resp = _invite(client_local, org)
    assert resp.status_code == 200
    assert len(mail.outbox) == 1
    toast = json.loads(resp["HX-Trigger"])["tuckit:toast"]
    assert "emailed" in toast["message"]
    assert toast.get("tone") != "err"
    assert "not emailed" not in resp.content.decode()


@NO_MAIL
@pytest.mark.django_db
def test_an_unsent_invitation_says_that_instead(client_local, org):
    resp = _invite(client_local, org)
    assert resp.status_code == 200, "the invitation is still valid — only the mail failed"
    assert mail.outbox == []

    toast = json.loads(resp["HX-Trigger"])["tuckit:toast"]
    assert toast["tone"] == "err"
    assert "did not go out" in toast["message"]
    assert "copy the link" in toast["message"].lower(), "says what to do instead"


@NO_MAIL
@pytest.mark.django_db
def test_the_row_keeps_saying_it_after_the_toast_is_gone(client_local, org):
    """A toast lasts six seconds; "I invited them last week and they never
    heard" lasts until somebody asks."""
    _invite(client_local, org)
    body = client_local.get(f"/{org.slug}/settings/members").content.decode()
    assert "not emailed" in body


@pytest.mark.django_db
def test_a_delivered_invitation_does_not_wear_the_warning(client_local, org):
    _invite(client_local, org)
    body = client_local.get(f"/{org.slug}/settings/members").content.decode()
    assert "new@x.com" in body, "the invite is on the page at all"
    assert "not emailed" not in body
