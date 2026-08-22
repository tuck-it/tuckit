"""A person had no way to see a slice's priority.

The field, the ordering, the MCP surface and the policy all landed before any
screen showed the number -- so the board would have been sorting by something
invisible, which reads as the order being arbitrary.
"""

import pytest

from tuckit.core.models import Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.fixture
def area(org):
    return create_area(org, "Backend")


def _ranked(org, area, priority, title="Leak"):
    s = create_slice(org, area=area, title=title, spec="designed")
    Slice.objects.filter(id=s.id).update(priority=priority)
    return s


@pytest.mark.django_db
def test_a_ranked_slice_shows_its_number_on_the_board(client_local, org, area):
    _ranked(org, area, 1)

    html = client_local.get(f"/{org.slug}/areas/{area.slug}/").content.decode()

    assert "priority-badge" in html
    assert ">1<" in html


@pytest.mark.django_db
def test_an_unranked_slice_shows_no_badge_at_all(client_local, org, area):
    """Unset must not render as a number. A slice nobody ranked showing "3"
    would be the board inventing a decision no one made."""
    create_slice(org, area=area, title="Unranked", spec="designed")

    html = client_local.get(f"/{org.slug}/areas/{area.slug}/").content.decode()

    assert "priority-badge" not in html


@pytest.mark.django_db
def test_the_detail_view_shows_the_policy_line_for_that_number(client_local, org, area):
    """The number alone means nothing. Jira has had per-priority descriptions
    for years and shows them only to administrators; this is the half they
    miss -- the criteria reaching whoever is actually looking at the work."""
    org.priority_policy = "1 = money in hand this week\n2 = a date promised outside"
    org.save(update_fields=["priority_policy", "updated_at"])
    s = _ranked(org, area, 1)

    html = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "money in hand this week" in html


@pytest.mark.django_db
def test_the_detail_view_shows_only_the_line_for_ITS_number(client_local, org, area):
    """Rendering the whole policy on every slice would be the same paragraph
    repeated on every screen, and would bury the one line that applies."""
    org.priority_policy = "1 = money in hand this week\n2 = a date promised outside"
    org.save(update_fields=["priority_policy", "updated_at"])
    s = _ranked(org, area, 2)

    html = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "a date promised outside" in html
    assert "money in hand this week" not in html


@pytest.mark.django_db
def test_an_empty_policy_renders_the_number_and_nothing_else(client_local, org, area):
    """An unwritten policy is a normal state, not a broken one -- and the bare
    number is the most honest prompt to go write one."""
    s = _ranked(org, area, 2)

    html = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "priority-badge" in html


@pytest.mark.django_db
def test_the_badge_never_names_a_tier(client_local, org, area):
    """The NUMBERS are the vocabulary and the policy supplies their meaning.
    Shipping "Urgent"/"High" would put a second vocabulary on the same screen
    as whatever the person wrote in their policy, and a classifying agent would
    have two things to obey.
    """
    org.priority_policy = "1 = money in hand this week"
    org.save(update_fields=["priority_policy", "updated_at"])
    s = _ranked(org, area, 1)

    html = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    for invented in ("Urgent", "Highest", "Trivial"):
        assert invented not in html
