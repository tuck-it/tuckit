import re

from tuckit.core.services.exceptions import InvalidValue

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_MIN, _MAX = 2, 32

RESERVED_ORG_SLUGS = {
    "settings", "login", "logout", "register", "invite", "welcome",
    "healthcheck", "cloud", "static", "media", "account", "check-slug",
    "admin", "api", "app", "www", "assets", "about", "help", "support",
    "status", "docs", "blog", "pricing", "terms", "privacy", "mail",
    "new", "me", "null", "undefined", "first-org",
}

RESERVED_WORKSPACE_SLUGS = {
    "settings", "new", "rename", "delete", "members", "workspaces", "invites",
}

_RESERVED = {"org": RESERVED_ORG_SLUGS, "workspace": RESERVED_WORKSPACE_SLUGS}


def normalize_slug(raw: str) -> str:
    return (raw or "").strip().lower()


def validate_slug(raw: str, *, kind: str) -> str:
    slug = normalize_slug(raw)
    if not (_MIN <= len(slug) <= _MAX):
        raise InvalidValue(f"The URL must be {_MIN}–{_MAX} characters.")
    if "--" in slug or not _SLUG_RE.match(slug):
        raise InvalidValue(
            "Use lowercase letters, numbers, and hyphens only — "
            "no leading, trailing, or repeated hyphens."
        )
    if slug in _RESERVED[kind]:
        raise InvalidValue(f"'{slug}' is reserved and can't be used.")
    return slug
