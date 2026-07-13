import re

from tuckit.core.services.exceptions import InvalidValue

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_MIN, _MAX = 2, 32

RESERVED_ORG_SLUGS = {
    "settings", "login", "logout", "register", "invite", "welcome",
    "healthcheck", "cloud", "static", "media", "account", "check-slug",
    "admin", "api", "app", "www", "assets", "about", "help", "support",
    "status", "docs", "blog", "pricing", "terms", "privacy", "mail",
    "new", "me", "null", "undefined",
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
        raise InvalidValue(f"슬러그는 {_MIN}~{_MAX}자여야 합니다")
    if "--" in slug or not _SLUG_RE.match(slug):
        raise InvalidValue("슬러그는 소문자·숫자·하이픈만 쓸 수 있으며 하이픈으로 시작/끝나거나 연속될 수 없습니다")
    if slug in _RESERVED[kind]:
        raise InvalidValue(f"'{slug}' 는 예약어라 사용할 수 없습니다")
    return slug
