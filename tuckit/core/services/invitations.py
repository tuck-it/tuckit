import secrets

from django.db import transaction
from django.utils import timezone

from tuckit.core.entitlements import assert_can_add_seat
from tuckit.core.models import Invitation, OrgMember, User
from tuckit.core.services.exceptions import InvalidValue, NotFound


def create_invitation(*, org, email, role, invited_by) -> Invitation:
    if OrgMember.objects.filter(org=org, user__email__iexact=email).exists():
        raise InvalidValue("Already a member of this organization")
    assert_can_add_seat(org)
    return Invitation.objects.create(
        org=org, email=email, role=role, token=secrets.token_urlsafe(32), invited_by=invited_by
    )


def get_pending_invitation(token) -> Invitation:
    inv = Invitation.objects.select_related("org").filter(token=token, accepted_at__isnull=True).first()
    if inv is None:
        raise NotFound("This invitation is invalid or has already been used")
    return inv


@transaction.atomic
def accept_invitation(*, token, user) -> OrgMember:
    inv = (
        Invitation.objects.select_for_update()
        .select_related("org")
        .filter(token=token, accepted_at__isnull=True)
        .first()
    )
    if inv is None:
        raise NotFound("This invitation is invalid or has already been used")
    if user.email.lower() != inv.email.lower():
        raise InvalidValue("The invited email does not match your login email")
    if OrgMember.objects.filter(user=user, org=inv.org).exists():
        raise InvalidValue("Already a member of this organization")
    # The check above only rules out an ACTIVE membership; an ended one still
    # occupies the unique (user, org) slot, so create() here would raise
    # IntegrityError. Resurrecting that row rather than opening a second one is
    # also what keeps a returning person's authorship one continuous thread.
    # home_seen_at resets to NULL so the time they were away does not arrive as
    # unread — NULL is already defined as badge-nothing (models/org.py).
    member = OrgMember.all_objects.filter(user=user, org=inv.org).first()
    if member is None:
        member = OrgMember.objects.create(user=user, org=inv.org, role=inv.role)
    else:
        member.role = inv.role
        member.ended_at = None
        member.home_seen_at = None
        member.save(update_fields=["role", "ended_at", "home_seen_at"])
    inv.accepted_at = timezone.now()
    inv.save(update_fields=["accepted_at"])
    return member


@transaction.atomic
def register_invited(*, invitation, password) -> tuple[User, OrgMember]:
    from tuckit.core.services.accounts import create_account  # local: avoid import cycle

    user = create_account(email=invitation.email, password=password)
    member = accept_invitation(token=invitation.token, user=user)
    return user, member


def cancel_invitation(*, org, invitation_id) -> None:
    Invitation.objects.filter(org=org, pk=invitation_id, accepted_at__isnull=True).delete()


def send_invitation_email(*, invitation, link) -> None:
    """Email the invite link. Raises MailNotSent if it did not go.

    The link shown in-app remains the source of truth, and the invitation is
    valid whether or not this succeeds — a self-host with no mail server copies
    the link by hand, which is a fine way to invite somebody.

    What is NOT fine is what this used to do. `fail_silently=True` meant that a
    deployment with no mail server, or a wrong password, or a rejected sender,
    all looked exactly like a delivered invitation: the row appeared, the
    inviter moved on, and the invitee never heard anything. Whether the mail
    went is now the caller's to report, and every caller has somewhere to
    report it.
    """
    from tuckit.core.services.mail import send

    send(
        subject=f"[{invitation.org.name}] Organization invitation",
        body=(
            f"You've been invited to the {invitation.org.name} organization.\n\n"
            f"Accept invitation: {link}"
        ),
        to=invitation.email,
    )
    invitation.emailed_at = timezone.now()
    invitation.save(update_fields=["emailed_at"])
