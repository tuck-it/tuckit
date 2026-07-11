import secrets

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import Invitation, OrgMember, User
from core.services.exceptions import InvalidValue, NotFound


def create_invitation(*, org, email, role, invited_by) -> Invitation:
    if OrgMember.objects.filter(org=org, user__email__iexact=email).exists():
        raise InvalidValue("이미 이 조직의 멤버입니다")
    return Invitation.objects.create(
        org=org, email=email, role=role, token=secrets.token_urlsafe(32), invited_by=invited_by
    )


def get_pending_invitation(token) -> Invitation:
    inv = Invitation.objects.select_related("org").filter(token=token, accepted_at__isnull=True).first()
    if inv is None:
        raise NotFound("초대가 유효하지 않거나 이미 사용되었습니다")
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
        raise NotFound("초대가 유효하지 않거나 이미 사용되었습니다")
    if user.email.lower() != inv.email.lower():
        raise InvalidValue("초대된 이메일과 로그인 이메일이 다릅니다")
    if OrgMember.objects.filter(user=user, org=inv.org).exists():
        raise InvalidValue("이미 이 조직의 멤버입니다")
    member = OrgMember.objects.create(user=user, org=inv.org, role=inv.role)
    inv.accepted_at = timezone.now()
    inv.save(update_fields=["accepted_at"])
    return member


@transaction.atomic
def register_invited(*, invitation, password, username=None) -> tuple[User, OrgMember]:
    username = username or invitation.email
    if User.objects.filter(username=username).exists():
        raise InvalidValue(f"User already exists: {username}")
    if not password:
        raise InvalidValue("비밀번호를 입력해 주세요")
    user = User(username=username, email=invitation.email)
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise InvalidValue(" ".join(exc.messages))
    user.set_password(password)
    user.save()
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
        subject=f"[{invitation.org.name}] 조직 초대",
        message=f"{invitation.org.name} 조직에 초대되었습니다.\n\n수락 링크: {link}",
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[invitation.email],
        fail_silently=True,
    )
