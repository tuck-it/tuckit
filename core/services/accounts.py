from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import Org, OrgMember, User, Workspace
from core.services.exceptions import InvalidValue
from core.services.hooks import run_signup_hook
from core.services.orgs import create_workspace


@transaction.atomic
def register(*, email, org_name, slug, password, username=None) -> tuple[User, Org, Workspace]:
    username = username or email
    if User.objects.filter(username=username).exists():
        raise InvalidValue(f"User already exists: {username}")
    if Org.objects.filter(slug=slug).exists():
        raise InvalidValue(f"Org slug already taken: {slug}")

    if not password:
        raise InvalidValue("비밀번호를 입력해 주세요")
    user = User(username=username, email=email)
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise InvalidValue(" ".join(exc.messages))
    user.set_password(password)
    user.save()

    org = Org.objects.create(name=org_name, slug=slug)
    OrgMember.objects.create(user=user, org=org, role="owner")
    workspace = create_workspace(org, org_name)

    run_signup_hook(user=user, org=org)
    return user, org, workspace
