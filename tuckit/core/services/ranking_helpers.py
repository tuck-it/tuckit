from tuckit.core.ranking import rank_between


def rank_for(model, filters: dict, before=None, after=None) -> str:
    """Fractional rank for a new/moved row among siblings `model.objects.filter(**filters)`.

    `after`  -> place immediately after that sibling.
    `before` -> place immediately before that sibling.
    neither  -> append at the end.
    """
    qs = model.objects.filter(**filters)
    if after is not None:
        lo = after.rank
        nxt = qs.filter(rank__gt=lo).order_by("rank").first()
        return rank_between(lo, nxt.rank if nxt else None)
    if before is not None:
        hi = before.rank
        prev = qs.filter(rank__lt=hi).order_by("-rank").first()
        return rank_between(prev.rank if prev else None, hi)
    last = qs.order_by("-rank").first()
    return rank_between(last.rank if last else None, None)
