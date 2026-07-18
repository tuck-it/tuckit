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
    member = OrgMember.objects.create(user=user, org=inv.org, role=inv.role)
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
    """Optional convenience: email the invite link. The link (shown in-app) is the
    source of truth; if no mail backend is configured, this fails silently and the
    self-host operator just copies the link. Never required."""
    from django.conf import settings
    from django.core.mail import send_mail

    send_mail(
        subject=f"[{invitation.org.name}] Organization invitation",
        message=f"You've been invited to the {invitation.org.name} organization.\n\nAccept invitation: {link}",
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[invitation.email],
        fail_silently=True,
    )
