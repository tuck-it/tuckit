"""Short, human-facing org key — the 'TUC' in 'TUC-47'.

Deliberately mirrors how Linear suggests a team key from the team name: the
derivation is only a suggestion, and the org can edit it in Settings. Kept free
of model imports so both `Org.save()` and (a copy of) a data migration can use
the same rules without an import cycle.
"""

import re

from tuckit.core.services.exceptions import InvalidValue

KEY_MIN, KEY_MAX = 2, 6
_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]*$")
_FALLBACK = "ORG"


def derive_key(slug: str) -> str:
    """Suggest a key from an org slug. Always returns something valid."""
    words = [w for w in (slug or "").split("-") if w]
    if len(words) >= 2:
        raw = "".join(w[0] for w in words[:4])
    elif words:
        # Strip a leading digit *before* truncating to 3 — otherwise a slug
        # like "1abc" loses a real letter to the digit instead of the digit
        # itself (slicing "1abc"[:3] first would keep "1ab", not "abc").
        raw = re.sub(r"^[^a-zA-Z]+", "", words[0])[:3]
    else:
        raw = ""
    raw = raw.upper()
    # An org slug may start with a digit (`^[a-z0-9]`), but a key may not —
    # drop leading non-letters rather than emitting something that fails its
    # own validator.
    raw = re.sub(r"^[^A-Z]+", "", raw)
    raw = re.sub(r"[^A-Z0-9]", "", raw)
    return raw if len(raw) >= KEY_MIN else _FALLBACK


def unique_key(base: str, taken) -> str:
    """First free key: base, then base2, base3… Truncates the STEM rather than
    overflowing KEY_MAX, so 'ABCDEF' collides into 'ABCDE2', not 'ABCDEF2'."""
    used = {(k or "").upper() for k in taken}
    if base not in used:
        return base
    n = 2
    while True:
        suffix = str(n)
        candidate = f"{base[: KEY_MAX - len(suffix)]}{suffix}"
        if candidate not in used:
            return candidate
        n += 1


def validate_key(raw: str) -> str:
    """Normalise and validate a human-entered key. Raises InvalidValue."""
    key = (raw or "").strip().upper()
    if not (KEY_MIN <= len(key) <= KEY_MAX):
        raise InvalidValue(f"The key must be {KEY_MIN}–{KEY_MAX} characters.")
    if not _KEY_RE.match(key):
        raise InvalidValue("Use letters and numbers only, starting with a letter.")
    return key
