"""Mail either goes or says why. It never quietly evaporates.

`fail_silently=True` on the one send in the product meant that "no mail server
configured", "wrong password" and "delivered" were the same observable event.
Invitations had been going nowhere since invitations existed, and the only
evidence was an invitee who never got in touch.
"""
import pathlib
import re

import pytest
from django.core import mail
from django.test import override_settings

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.invitations import create_invitation, send_invitation_email
from tuckit.core.services.mail import MailNotSent, email_is_configured, send

# Django's test setup swaps in the locmem backend, which needs no host — so the
# default state of these tests is "mail works". Unconfigured has to be asked for.
NO_MAIL = override_settings(
    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    EMAIL_HOST="",
    DEFAULT_FROM_EMAIL="",
)


def _org_and_owner():
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(username="o@a.com", email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    return org, owner


# ------------------------------------------------------------ configured or not

def test_a_deployment_with_no_mail_server_knows_it():
    with NO_MAIL:
        assert email_is_configured() is False


def test_a_deployment_with_a_host_and_a_sender_knows_it():
    with override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="tuckit@example.test",
    ):
        assert email_is_configured() is True


def test_a_host_with_no_sender_address_is_not_configured():
    """Mail from an address the domain has not authorised lands in spam, which
    is indistinguishable from not sending it."""
    with override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="",
    ):
        assert email_is_configured() is False


def test_the_console_backend_a_developer_runs_needs_no_host():
    with override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend"):
        assert email_is_configured() is True


# ------------------------------------------------------------ send

def test_send_refuses_out_loud_when_nothing_is_configured():
    with NO_MAIL, pytest.raises(MailNotSent) as exc:
        send(subject="s", body="b", to="x@y.com")
    assert "No mail server is configured" in str(exc.value)


def test_send_delivers_when_it_can():
    send(subject="Hello", body="Body", to="x@y.com")
    assert [m.subject for m in mail.outbox] == ["Hello"]


# ------------------------------------------------------------ invitations

@pytest.mark.django_db
def test_an_invitation_email_goes_out_and_is_recorded():
    org, owner = _org_and_owner()
    inv = create_invitation(org=org, email="new@x.com", role="member", invited_by=owner)
    send_invitation_email(invitation=inv, link="https://example.test/i/abc")

    assert len(mail.outbox) == 1
    assert "https://example.test/i/abc" in mail.outbox[0].body
    inv.refresh_from_db()
    assert inv.emailed_at is not None


@pytest.mark.django_db
def test_a_failed_invitation_email_is_raised_and_leaves_no_false_record():
    org, owner = _org_and_owner()
    inv = create_invitation(org=org, email="new@x.com", role="member", invited_by=owner)
    with NO_MAIL, pytest.raises(MailNotSent):
        send_invitation_email(invitation=inv, link="https://example.test/i/abc")

    inv.refresh_from_db()
    assert inv.emailed_at is None, "an unsent invitation must not read as sent"


@pytest.mark.django_db
def test_the_invitation_itself_survives_a_mail_failure():
    """The link shown in-app has always been the source of truth. A missing mail
    server is a reason to say so, not a reason to refuse to invite anybody."""
    org, owner = _org_and_owner()
    inv = create_invitation(org=org, email="new@x.com", role="member", invited_by=owner)
    with NO_MAIL:
        with pytest.raises(MailNotSent):
            send_invitation_email(invitation=inv, link="https://example.test/i/abc")
    assert org.invitations.filter(email="new@x.com").exists()


# ------------------------------------------------------------ the flag itself

# Matches the keyword as an ARGUMENT — after an open paren or a comma, or alone
# on its own line — so that the several places that discuss the flag in prose do
# not trip it. Naming a mistake is how it stays fixed.
_FAIL_SILENTLY = re.compile(r"(?:[(,]\s*|^\s*)fail_silently\s*=\s*True", re.M)


def test_nothing_in_the_codebase_sends_with_fail_silently_again():
    """The whole bug in one keyword argument. It reads as "this is optional"
    and means "discard every failure, including there being no server"."""
    offenders = [
        str(path)
        for path in pathlib.Path("tuckit").rglob("*.py")
        if _FAIL_SILENTLY.search(path.read_text())
    ]
    assert not offenders, offenders


def test_the_guard_would_actually_catch_it():
    """A regex guard that matches nothing passes forever."""
    assert _FAIL_SILENTLY.search("send_mail(x, fail_silently=True)")
    assert _FAIL_SILENTLY.search("    fail_silently=True,\n")
    assert not _FAIL_SILENTLY.search("# we used to pass `fail_silently=True` here")
