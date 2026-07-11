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

    user = User(username=username, email=email)
    user.set_password(password)
    user.save()

    org = Org.objects.create(name=org_name, slug=slug)
    OrgMember.objects.create(user=user, org=org, role="owner")
    workspace = create_workspace(org, org_name)

    run_signup_hook(user=user, org=org)
    return user, org, workspace
