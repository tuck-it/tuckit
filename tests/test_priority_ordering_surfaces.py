"""Every surface that shows slices must order by priority, or the board
disagrees with itself depending on which screen you are looking at.

The constraints on TP-178 put it plainly: miss one call site and the board is
inconsistent with itself. The plan named four; the repo had eight. These tests
exist so the ninth cannot be added quietly.
"""

import pathlib
import re

import pytest

from tuckit.core.models import Org, Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice, grouped_slices
from tuckit.core.services.state import (
    area_board_view,
    home_state,
    roadmap_board_view,
    roadmap_state,
)

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def board():
    """One area, three open slices: unranked, priority 4, priority 1.

    Created in that order so plain rank order ("Unranked", "Low", "Top") is the
    exact reverse of what priority ordering must produce. A surface that
    forgets priority therefore fails loudly rather than coincidentally passing.
    """
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    # A written spec on all three: stage is derived from spec + bites, and with
    # an empty one every slice sits at needs_design, which is not the band the
    # home test needs.
    unranked = create_slice(org, area=area, title="Unranked", spec="designed")
    low = create_slice(org, area=area, title="Low", spec="designed")
    top = create_slice(org, area=area, title="Top", spec="designed")
    Slice.objects.filter(id=low.id).update(priority=4)
    Slice.objects.filter(id=top.id).update(priority=1)
    return org, area, (top, low, unranked)


@pytest.mark.django_db
def test_grouped_slices_orders_by_priority(board):
    """The area screen's grouped list. It reads Meta.ordering, which is
    rank-only, so this surface needed the ordering spelled out."""
    org, area, _ = board

    open_titles = [s.title for status, rows in grouped_slices(area)
                   for s in rows if status == "open"]

    assert open_titles == ["Top", "Low", "Unranked"]


@pytest.mark.django_db
def test_area_board_view_orders_each_column_by_priority(board):
    """The area kanban. annotate_stage_counts drops Meta.ordering here, so an
    implicit order would not merely be rank -- it would be undefined."""
    org, area, _ = board

    groups = area_board_view(area)["groups"]
    ordered = [s.title for _key, rows in groups for s in rows]

    assert ordered == ["Top", "Low", "Unranked"]


@pytest.mark.django_db
def test_roadmap_board_view_orders_by_priority_within_an_area(board):
    org, _area, _ = board

    groups = roadmap_board_view(org)["groups"]
    ordered = [s.title for _key, rows in groups for s in rows]

    assert ordered == ["Top", "Low", "Unranked"]


@pytest.mark.django_db
def test_roadmap_state_buckets_order_by_priority(board):
    org, _area, _ = board

    assert [s.title for s in roadmap_state(org)["open"]] == ["Top", "Low", "Unranked"]


@pytest.mark.django_db
def test_home_in_progress_orders_by_priority_inside_the_stale_grouping(board):
    """home_state re-sorts this band in Python, which REPLACES the queryset's
    ordering. Adding order_by to the query was not enough; the sort key had to
    name priority too, and this is what catches it if someone removes it.

    Staleness and area stay ahead of priority -- they group the band -- so all
    three slices here share both and priority alone decides.
    """
    org, area, (top, low, unranked) = board
    # stage 'executing' is what this band collects: a slice with at least one
    # bite, not all done.
    from tuckit.core.services.bites import create_bite
    for s in (top, low, unranked):
        create_bite(s, "step")

    assert [s.title for s in home_state(org)["in_progress"]] == [
        "Top", "Low", "Unranked",
    ]


# --- structural guard -------------------------------------------------------
#
# The behavioural tests above pin the surfaces that exist today. This one is
# about the surface added next month: it fails if any slice-facing module goes
# back to ordering by bare rank.

SLICE_FACING = [
    "tuckit/core/services/slices.py",
    "tuckit/core/services/state.py",
    "tuckit/web/views/slices.py",
    "tuckit/web/views/pages.py",
]

# `rank` as the leading sort key, i.e. the pre-TP-178 ordering.
BARE_RANK = re.compile(r'order_by\(\s*(?:"area__name",\s*)?"rank"')


@pytest.mark.parametrize("relpath", SLICE_FACING)
def test_no_slice_surface_orders_by_bare_rank(relpath):
    """priority is the primary key and rank the tiebreaker inside it. A surface
    ordering by rank alone silently reverts that, and only for the screen it
    serves -- which is the hardest kind of inconsistency to notice, because
    every other screen still looks right.

    If you are adding a surface that genuinely must not use priority, do what
    your_turn() did: use a different key entirely and say why in a comment.
    """
    text = (REPO / relpath).read_text(encoding="utf-8")
    offenders = [line.strip() for line in text.splitlines() if BARE_RANK.search(line)]

    assert offenders == [], (
        f"{relpath} orders slices by bare rank: {offenders}. "
        f"Use PRIORITY_ORDER from tuckit.core.services.slices."
    )


def test_your_turn_is_still_the_documented_exception():
    """One surface deliberately ignores priority: the band that asks what has
    waited longest for a human. Burying a stalled low-priority slice there
    would hide exactly the state that most needs a person.

    Pinned because the guard above would otherwise pressure someone into
    "fixing" it, and the comment alone has no teeth.
    """
    text = (REPO / "tuckit/core/services/state.py").read_text(encoding="utf-8")
    your_turn = text.split("def your_turn(")[1].split("\ndef ")[0]

    assert '.order_by("updated_at")' in your_turn
    assert "Deliberately NOT PRIORITY_ORDER" in your_turn
