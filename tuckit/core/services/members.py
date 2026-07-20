from tuckit.core.models import OrgMember
from tuckit.core.services.exceptions import InvalidValue, NotFound


def resolve_member(org, spec: str, caller_user=None) -> OrgMember | None:
    """Resolve an assignee spec to an OrgMember of `org`.
    '' -> None (clear). 'me' -> the caller's member (requires caller_user).
    '<email>' -> that member. Raises NotFound / InvalidValue."""
    if spec == "":
        return None
    if spec == "me":
        if caller_user is None:
            raise InvalidValue("assignee 'me' requires a user-authenticated (OAuth) token")
        member = OrgMember.objects.filter(org=org, user=caller_user).first()
        if member is None:
            raise NotFound("caller is not a member of this org")
        return member
    member = OrgMember.objects.filter(org=org, user__email=spec).first()
    if member is None:
        raise NotFound(f"no org member with email {spec!r}")
    return member
