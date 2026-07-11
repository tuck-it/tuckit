from fractional_indexing import generate_key_between


def rank_between(a: str | None, b: str | None) -> str:
    """Return a rank key that sorts strictly between neighbors `a` and `b`.

    `a`/`b` are existing rank keys or None (None = open end). When both are
    given, callers must ensure `a < b`.
    """
    return generate_key_between(a, b)
