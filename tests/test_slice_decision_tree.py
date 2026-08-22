import pytest

from tuckit.core.models import CanvasWatch
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.slices import (
    choose_option,
    create_slice,
    propose_nodes,
    update_slice,
)
from tuckit.core.services.watches import open_watch


@pytest.mark.django_db
def test_decision_tree_defaults_to_an_empty_dict(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    s.refresh_from_db()
    assert s.decision_tree == {}


@pytest.mark.django_db
def test_decision_tree_round_trips_a_node_tree(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    s.decision_tree = {"nodes": [
        {"id": "n1", "parent": None, "kind": "question", "title": "Root",
         "summary": "", "body": "**bold**", "at": 1787200000000},
        {"id": "n2", "parent": "n1", "kind": "option", "title": "A",
         "summary": "s", "body": "", "recommended": True, "at": 1787200000001},
    ]}
    s.save(update_fields=["decision_tree"])
    s.refresh_from_db()

    assert s.decision_tree["nodes"][0]["parent"] is None
    assert s.decision_tree["nodes"][0]["body"] == "**bold**"
    assert s.decision_tree["nodes"][1]["recommended"] is True


@pytest.mark.django_db
def test_writing_a_spec_keeps_the_decision_record(org, area):
    """The record of HOW a design was decided is not a draft of the design.
    Writing the spec used to destroy it, with no way to get it back."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [{"id": "n1", "parent": None, "kind": "question", "title": "Q"}])

    update_slice(s, spec="## Decision\nWe went with A.")

    s.refresh_from_db()
    assert s.spec.startswith("## Decision")
    assert [n["id"] for n in s.decision_tree["nodes"]] == ["n1"]


@pytest.mark.django_db
def test_an_empty_spec_leaves_the_decision_tree_alone(org, area):
    """`spec=""` is 'not designed yet', which is exactly when the decision_tree is the
    only record of the thinking. Clearing it there would delete the work."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [{"id": "n1", "parent": None, "kind": "question", "title": "Q"}])

    update_slice(s, spec="   ")

    s.refresh_from_db()
    assert [n["id"] for n in s.decision_tree["nodes"]] == ["n1"]


@pytest.mark.django_db
def test_an_unrelated_update_leaves_the_decision_tree_alone(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [{"id": "n1", "parent": None, "kind": "question", "title": "Q"}])

    update_slice(s, title="Canvas, renamed")

    s.refresh_from_db()
    assert [n["id"] for n in s.decision_tree["nodes"]] == ["n1"]


@pytest.mark.django_db
def test_writing_a_spec_still_closes_open_watches(org, area):
    """Keeping the record is not the same as keeping the question open. A click
    channel with no open question answers nothing."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [{"id": "q1", "parent": None, "kind": "question", "title": "Q"}])
    open_watch(s, question_id="q1")

    update_slice(s, spec="## Decided\nthe design")

    assert not CanvasWatch.objects.filter(slice=s).exists()


@pytest.mark.django_db
def test_a_written_spec_still_closes_the_record_to_new_writes(org, area):
    """The record survives, and it freezes. Reopening it is a separate question
    (TP-240), not something to pick up in passing here."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [
        {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "Left"},
    ])
    update_slice(s, spec="## Decided\nthe design")
    s.refresh_from_db()

    with pytest.raises(InvalidValue):
        propose_nodes(s, [{"id": "o2", "parent": "q1", "kind": "option", "title": "Right"}])
    with pytest.raises(InvalidValue):
        choose_option(s, "o1")

    # ...and the record is still all there after both rejections.
    s.refresh_from_db()
    assert [n["id"] for n in s.decision_tree["nodes"]] == ["q1", "o1"]
