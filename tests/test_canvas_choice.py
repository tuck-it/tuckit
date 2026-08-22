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


def _canvas(org, area, extra=()):
    s = create_slice(org, area=area, title="Canvas", spec="")
    nodes = [{"id": "q1", "parent": None, "kind": "question", "title": "which?"},
             {"id": "o1", "parent": "q1", "kind": "option", "title": "a"},
             {"id": "o2", "parent": "q1", "kind": "option", "title": "b"}]
    s.decision_tree = {"nodes": nodes + list(extra)}
    s.save(update_fields=["decision_tree"])
    return s


@pytest.mark.django_db
def test_a_misclick_can_be_corrected_while_nothing_has_been_built_on_it(org, area):
    s = _canvas(org, area)
    choose_option(s, "o2")

    choose_option(s, "o1")

    s.refresh_from_db()
    q1 = next(n for n in s.decision_tree["nodes"] if n["id"] == "q1")
    assert q1["chosen"] == "o1"


@pytest.mark.django_db
def test_the_question_locks_once_the_answer_has_children(org, area):
    s = _canvas(org, area, extra=[
        {"id": "d1", "parent": "o2", "kind": "note", "title": "because"}])
    choose_option(s, "o2")

    with pytest.raises(InvalidValue) as e:
        choose_option(s, "o1")

    assert "locked" in str(e.value).lower()
    s.refresh_from_db()
    q1 = next(n for n in s.decision_tree["nodes"] if n["id"] == "q1")
    assert q1["chosen"] == "o2"          # the snapshot is intact


@pytest.mark.django_db
def test_a_locked_question_still_rejects_even_when_the_spec_is_empty(org, area):
    # The lock is about children, not about the spec. Guarding only on the
    # spec was the old rule, and it let two days of work be re-attributed.
    s = _canvas(org, area, extra=[
        {"id": "d1", "parent": "o2", "kind": "note", "title": "because"}])
    choose_option(s, "o2")
    assert s.spec == ""

    with pytest.raises(InvalidValue):
        choose_option(s, "o1")


@pytest.mark.django_db
def test_a_written_spec_still_seals_the_record(org, area):
    s = _canvas(org, area)
    s.spec = "designed"
    s.save(update_fields=["spec"])

    with pytest.raises(InvalidValue):
        choose_option(s, "o1")
