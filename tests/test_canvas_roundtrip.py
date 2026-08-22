import pytest

from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.slices import (
    choose_option, create_slice, propose_nodes, update_slice,
)
from tuckit.core.services.watches import open_watch, read_watch


def _tree(slice_):
    propose_nodes(slice_, [
        {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "Left"},
        {"id": "o2", "parent": "q1", "kind": "option", "title": "Right"},
    ])


@pytest.mark.django_db
def test_a_choice_reaches_the_watch(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)
    _, raw = open_watch(s)

    choose_option(s, "o2")

    assert read_watch(raw) == {"status": "chosen", "choice": "o2"}


@pytest.mark.django_db
def test_a_choice_never_reaches_another_slice_s_watch(org, area):
    mine = create_slice(org, area=area, title="Mine", spec="")
    theirs = create_slice(org, area=area, title="Theirs", spec="")
    _tree(mine)
    _, raw = open_watch(theirs)

    choose_option(mine, "o2")

    assert read_watch(raw) == {"status": "waiting"}


@pytest.mark.django_db
def test_writing_the_spec_retires_the_channel(org, area):
    """The design stopped being open, so the channel is not a channel any
    more."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)
    _, raw = open_watch(s)

    update_slice(s, spec="## Decided\nWe went with Right.")

    assert read_watch(raw) is None


def _two_questions(slice_):
    propose_nodes(slice_, [
        {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        {"id": "q1o1", "parent": "q1", "kind": "option", "title": "Left"},
        {"id": "q1o2", "parent": "q1", "kind": "option", "title": "Right"},
        {"id": "q2", "parent": "q1o1", "kind": "question", "title": "How far?"},
        {"id": "q2o1", "parent": "q2", "kind": "option", "title": "A little"},
        {"id": "q2o2", "parent": "q2", "kind": "option", "title": "A lot"},
    ])


@pytest.mark.django_db
def test_a_click_on_one_question_does_not_answer_its_sibling(org, area):
    """Two questions on one slice is the normal flow (the skill calls propose
    per question, not once at the end), so two live watches at once is not an
    edge case. A click under Q2 must answer only Q2's watch and leave Q1's
    watch waiting -- the exact hop that silently failed before watches were
    scoped to a question."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    _two_questions(s)
    _, raw_q1 = open_watch(s, question_id="q1")
    _, raw_q2 = open_watch(s, question_id="q2")

    choose_option(s, "q2o2")

    # Q2's watch carries q2's answer, by node id -- not merely "answered".
    assert read_watch(raw_q2) == {"status": "chosen", "choice": "q2o2"}
    # Q1's watch is untouched: still waiting, not accidentally holding q2's id.
    assert read_watch(raw_q1) == {"status": "waiting"}


@pytest.mark.django_db
def test_a_later_click_on_the_first_question_still_reaches_its_own_watch(org, area):
    """This is the hop that silently failed today: after Q2 is answered, a
    click on Q1 must still reach Q1's watch -- not find `choice` already
    non-empty (from the old unscoped filter) and match nothing."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    _two_questions(s)
    _, raw_q1 = open_watch(s, question_id="q1")
    _, raw_q2 = open_watch(s, question_id="q2")
    choose_option(s, "q2o2")

    choose_option(s, "q1o1")

    assert read_watch(raw_q1) == {"status": "chosen", "choice": "q1o1"}
    # Still holds its own, earlier answer -- unaffected by the later click.
    assert read_watch(raw_q2) == {"status": "chosen", "choice": "q2o2"}


@pytest.mark.django_db
def test_an_empty_spec_is_not_a_written_one(org, area):
    """'' means "still being designed". Retiring the watch there would kill the
    channel in the middle of the conversation it exists for -- the same rule
    that stops an empty spec wiping the decision_tree."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)
    _, raw = open_watch(s)

    update_slice(s, spec="   ")

    assert read_watch(raw) == {"status": "waiting"}


@pytest.mark.django_db
def test_a_failing_update_leaves_the_watch_alive(org, area):
    """close_watches() must share the fate of the write it belongs to. Before
    this was moved inside the atomic block, an update_slice() call that wrote
    a spec AND an invalid status deleted the watches immediately -- outside
    the transaction, before validate_choice ever ran -- and then raised and
    left the spec unwritten. The watch must not be a casualty of a write that
    never actually landed."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)
    _, raw = open_watch(s)

    with pytest.raises(InvalidValue):
        update_slice(s, spec="## Decided\nWe went with Right.", status="bogus")

    s.refresh_from_db()
    assert s.spec == ""  # the write never landed
    assert read_watch(raw) == {"status": "waiting"}  # nor did the delete
