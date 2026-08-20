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
    assert [n["id"] for n in s.draft["nodes"]] == ["n1", "n2"]
    assert all(isinstance(n["at"], int) and n["at"] > 0 for n in added)


@pytest.mark.django_db
def test_a_later_call_appends_instead_of_replacing(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [_n("n1")])

    propose_nodes(s, [_n("n2", "n1")])

    s.refresh_from_db()
    assert [n["id"] for n in s.draft["nodes"]] == ["n1", "n2"]


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
    assert [n["id"] for n in s.draft["nodes"]] == ["n1"]


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
