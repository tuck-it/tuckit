import pytest

from tuckit.core.models import ActivityEvent
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.slices import create_slice, propose_nodes


def _n(node_id, parent=None, **extra):
    return {"id": node_id, "parent": parent, "kind": "note", "title": node_id, **extra}


@pytest.mark.django_db
def test_a_first_call_seeds_the_root_and_stamps_arrival(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")

    added = propose_nodes(s, [_n("n1"), _n("n2", "n1", kind="option")])

    s.refresh_from_db()
    assert [n["id"] for n in s.decision_tree["nodes"]] == ["n1", "n2"]
    assert all(isinstance(n["at"], int) and n["at"] > 0 for n in added)


@pytest.mark.django_db
def test_a_later_call_appends_instead_of_replacing(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [_n("n1")])

    propose_nodes(s, [_n("n2", "n1")])

    s.refresh_from_db()
    assert [n["id"] for n in s.decision_tree["nodes"]] == ["n1", "n2"]


@pytest.mark.django_db
def test_the_server_owns_arrival_time(org, area):
    """The client staggers the entrance on `at`. A caller-supplied value would
    let an agent fake the order it thought of things in."""
    s = create_slice(org, area=area, title="Canvas", spec="")

    added = propose_nodes(s, [_n("n1", at=1)])

    assert added[0]["at"] != 1


@pytest.mark.django_db
def test_proposing_never_writes_chosen(org, area):
    """`chosen` records a human's pick. An agent able to write it would be
    choosing on the human's behalf."""
    s = create_slice(org, area=area, title="Canvas", spec="")

    added = propose_nodes(s, [_n("n1", chosen="n2")])

    assert "chosen" not in added[0]


@pytest.mark.django_db
def test_a_slice_that_already_has_a_spec_refuses_proposals(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="## Decided\ntext")

    with pytest.raises(InvalidValue):
        propose_nodes(s, [_n("n1")])


@pytest.mark.django_db
def test_a_duplicate_id_is_refused(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [_n("n1")])

    with pytest.raises(InvalidValue):
        propose_nodes(s, [_n("n1")])


@pytest.mark.django_db
@pytest.mark.parametrize("bad", [
    {"id": "", "parent": "n1"},              # no id
    {"id": "n9", "parent": "nope"},          # parent is not on the canvas
    {"id": "n9", "parent": "n1", "kind": "banana"},
    {"id": "n9", "parent": None},            # a second root
])
def test_a_malformed_node_rejects_the_whole_batch(org, area, bad):
    """Half-applying a proposal would leave a canvas nobody wrote and nobody
    can reason about."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [_n("n1")])

    with pytest.raises(InvalidValue):
        propose_nodes(s, [_n("n2", "n1"), bad])

    s.refresh_from_db()
    assert [n["id"] for n in s.decision_tree["nodes"]] == ["n1"]


@pytest.mark.django_db
def test_proposing_records_activity_so_the_poller_wakes(org, area):
    """live.js polls the org activity cursor. With no row here the canvas only
    updates on a manual reload -- bite 4 rides this event."""
    s = create_slice(org, area=area, title="Canvas", spec="")

    propose_nodes(s, [_n("n1"), _n("n2", "n1")], source="agent")

    ev = ActivityEvent.objects.filter(verb="proposed").get()
    assert ev.target_id == s.id
    assert ev.source == "agent"
    assert ev.to_value == "2"


def _answered(org, area):
    """A slice whose q1 is answered with o1."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [_n("q1", kind="question"),
                      _n("o1", "q1", kind="option"),
                      _n("o2", "q1", kind="option")])
    nodes = s.decision_tree["nodes"]
    next(n for n in nodes if n["id"] == "q1")["chosen"] = "o1"
    s.decision_tree = {"nodes": nodes}
    s.save(update_fields=["decision_tree"])
    return s


@pytest.mark.django_db
def test_progress_may_not_hang_off_a_question_that_was_already_answered(org, area):
    s = _answered(org, area)

    with pytest.raises(InvalidValue) as e:
        propose_nodes(s, [_n("d1", "q1")])

    # The value of the guard is that it names the right parent. A test that
    # only asserts "it raised" proves nothing an agent could act on.
    assert "'o1'" in str(e.value)
    assert "q1" in str(e.value)


@pytest.mark.django_db
def test_more_options_may_still_be_added_to_an_answered_question(org, area):
    # The guard blocks PROGRESS, not candidates.
    s = _answered(org, area)

    propose_nodes(s, [_n("o3", "q1", kind="option")])

    s.refresh_from_db()
    assert any(n["id"] == "o3" for n in s.decision_tree["nodes"])


@pytest.mark.django_db
def test_progress_may_not_hang_off_an_option_that_did_not_win(org, area):
    # The race: the human clicks o2, the agent starts working, the human
    # corrects to o1 three seconds later. Guard 1 lets parent=o2 through --
    # o2 IS an option -- so this second guard is what catches it.
    s = _answered(org, area)

    with pytest.raises(InvalidValue) as e:
        propose_nodes(s, [_n("d1", "o2")])

    assert "'o1'" in str(e.value)


@pytest.mark.django_db
def test_progress_may_not_hang_off_an_option_while_the_question_is_open(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [_n("q1", kind="question"), _n("o1", "q1", kind="option")])

    with pytest.raises(InvalidValue) as e:
        propose_nodes(s, [_n("d1", "o1")])

    assert "no answer yet" in str(e.value)


@pytest.mark.django_db
def test_progress_under_the_winning_option_is_accepted(org, area):
    s = _answered(org, area)

    propose_nodes(s, [_n("d1", "o1")])

    s.refresh_from_db()
    assert any(n["id"] == "d1" for n in s.decision_tree["nodes"])


@pytest.mark.django_db
def test_a_rejected_batch_stores_none_of_itself(org, area):
    s = _answered(org, area)

    with pytest.raises(InvalidValue):
        propose_nodes(s, [_n("ok", "o1"), _n("bad", "q1")])

    s.refresh_from_db()
    assert not any(n["id"] == "ok" for n in s.decision_tree["nodes"])


@pytest.mark.django_db
def test_a_new_option_in_this_batch_cannot_carry_progress_either(org, area):
    # The hole the first two guards left: q1 is answered with o1, and one call
    # adds a fresh option o3 plus a note under it. o3 exists only inside this
    # batch, so a lookup built from stored nodes alone never sees it -- and a
    # node lands under an option that did not win.
    s = _answered(org, area)

    with pytest.raises(InvalidValue) as e:
        propose_nodes(s, [_n("o3", "q1", kind="option"), _n("d1", "o3")])

    assert "'o1'" in str(e.value)
    s.refresh_from_db()
    assert not any(n["id"] == "o3" for n in s.decision_tree["nodes"])
