import pytest

from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.slugs import normalize_slug, validate_slug


def test_normalize_trims_and_lowercases():
    assert normalize_slug("  Acme ") == "acme"


@pytest.mark.parametrize("raw", ["acme", "my-team", "a1", "ab", "a" * 32])
def test_valid_slugs_pass(raw):
    assert validate_slug(raw, kind="org") == raw.lower()


@pytest.mark.parametrize("raw", [
    "Acme",            # uppercase (normalized then ok) -> actually becomes 'acme'
])
def test_uppercase_is_normalized_not_rejected(raw):
    assert validate_slug(raw, kind="org") == "acme"


@pytest.mark.parametrize("raw", [
    "a b",             # space
    "a_b",             # underscore
    "café",            # unicode
    "😀",              # emoji
    "-ab",             # leading hyphen
    "ab-",             # trailing hyphen
    "a--b",            # consecutive hyphen
    "a",               # too short
    "a" * 33,          # too long
    "",                # empty
])
def test_bad_format_rejected(raw):
    with pytest.raises(InvalidValue):
        validate_slug(raw, kind="org")


def test_org_reserved_rejected():
    for word in ["settings", "login", "cloud", "admin", "account", "check-slug"]:
        with pytest.raises(InvalidValue):
            validate_slug(word, kind="org")


def test_workspace_reserved_rejected():
    for word in ["settings", "new", "rename", "delete", "members", "workspaces"]:
        with pytest.raises(InvalidValue):
            validate_slug(word, kind="workspace")


def test_workspace_allows_words_reserved_only_for_org():
    # 'login' is an org reserved word but fine as a workspace slug
    assert validate_slug("login", kind="workspace") == "login"


def test_invites_reserved_for_workspace_but_fine_for_org():
    # /settings/<org>/invites is an org-level route; a workspace slug "invites"
    # would collide with it at the same path depth.
    with pytest.raises(InvalidValue):
        validate_slug("invites", kind="workspace")
    assert validate_slug("invites", kind="org") == "invites"


def test_first_org_is_reserved():
    with pytest.raises(InvalidValue):
        validate_slug("first-org", kind="org")
