import pytest

from tuckit.core.models import ActivityEvent
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.slices import choose_option, create_slice, propose_nodes


def _tree(slice_):
    propose_nodes(slice_, [
        {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "Left"},
        {"id": "o2", "parent": "q1", "kind": "option", "title": "Right"},
    ])


def _question(slice_):
    return next(n for n in slice_.decision_tree["nodes"] if n["id"] == "q1")


@pytest.mark.django_db
def test_choosing_marks_the_question_not_the_option(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)

    choose_option(s, "o2")

    s.refresh_from_db()
    assert _question(s)["chosen"] == "o2"
    # The option itself is untouched: "which one won" is a fact about the
    # question, and storing it twice would let the two disagree.
    assert "chosen" not in next(n for n in s.decision_tree["nodes"] if n["id"] == "o2")


@pytest.mark.django_db
def test_a_second_choice_replaces_the_first(org, area):
    """Nothing in this product is a one-way door, and a mis-click is real."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)

    choose_option(s, "o1")
    choose_option(s, "o2")

    s.refresh_from_db()
    assert _question(s)["chosen"] == "o2"


@pytest.mark.django_db
def test_choosing_records_activity_so_other_screens_see_it(org, area):
    # live.js polls the org activity cursor. With no row, a colleague's canvas
    # only learns about the choice on a manual reload.
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)

    choose_option(s, "o2")

    event = ActivityEvent.objects.filter(verb="chose").get()
    assert event.target_id == s.id
    assert event.to_value == "Right"


@pytest.mark.django_db
def test_only_an_option_can_be_chosen(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)

    with pytest.raises(InvalidValue):
        choose_option(s, "q1")


@pytest.mark.django_db
def test_an_unknown_node_is_refused(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)

    with pytest.raises(InvalidValue):
        choose_option(s, "nope")


@pytest.mark.django_db
def test_an_orphan_option_cannot_be_chosen(org, area):
    """An option whose parent is a note answers no question."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [
        {"id": "n1", "parent": None, "kind": "note", "title": "Context"},
        {"id": "o1", "parent": "n1", "kind": "option", "title": "Left"},
    ])

    with pytest.raises(InvalidValue):
        choose_option(s, "o1")


@pytest.mark.django_db
def test_a_written_spec_leaves_nothing_to_choose(org, area):
    """Same rule as propose_nodes: once a spec exists the record is closed to
    new writes. It is still drawn -- it is just read-only."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)
    s.spec = "## Decided\nWe went with Right."
    s.save(update_fields=["spec"])

    with pytest.raises(InvalidValue):
        choose_option(s, "o2")
