"""Sending mail, and being honest about not sending it.

Before this module, the only send in the product passed `fail_silently=True`.
That flag does not mean "this is optional" — it means every failure, including
"there is no mail server at all", is discarded without a log line. Invitations
had been going nowhere for as long as invitations had existed, and the only way
to find out was to ask the person who never got one.

So there are exactly two outcomes here and both are speakable: it went, or it
did not and this is why. Nothing swallows.
"""
from django.conf import settings
from django.core.mail import send_mail

# Backends that deliver somewhere real without any host configured — the
# console and file ones a developer runs, and the in-memory one tests use.
# Anything else needs an SMTP host before it can do anything at all.
_HOSTLESS_BACKENDS = (
    "django.core.mail.backends.console.EmailBackend",
    "django.core.mail.backends.filebased.EmailBackend",
    "django.core.mail.backends.locmem.EmailBackend",
)


class MailNotSent(Exception):
    """Raised when a message could not be handed to a mail server.

    Like WritesBlocked, the message is the point: it is shown to whoever
    triggered the send, so it has to say what to do next rather than only that
    something failed. Callers decide how much it matters — an invitation, for
    instance, is still a valid invitation with a link the inviter can copy.
    """


def email_is_configured() -> bool:
    """Can this deployment send mail at all?

    A question worth being able to ask before trying: a self-host with no mail
    server is a perfectly ordinary deployment, and the product should say
    "no mail server is configured" rather than surface a connection error from
    Django's default of SMTP-to-localhost:25.
    """
    if settings.EMAIL_BACKEND in _HOSTLESS_BACKENDS:
        return True
    return bool(settings.EMAIL_HOST and settings.DEFAULT_FROM_EMAIL)


def send(*, subject: str, body: str, to: str) -> None:
    """Send one plain-text message. Raises MailNotSent, never returns a bool.

    fail_silently is False on purpose and should stay that way. Anything that
    genuinely does not care whether the mail arrived can catch this; nothing
    should be able to not-care by accident.
    """
    if not email_is_configured():
        raise MailNotSent(
            "No mail server is configured for this deployment, so nothing was sent."
        )
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to],
            fail_silently=False,
        )
    except Exception as exc:  # smtplib, socket, ssl — the list is not worth enumerating
        raise MailNotSent(f"The mail server refused the message: {exc}") from exc
