from tuckit.core.services.canvas import (
    is_locked, question_state, reparented, spine_for)


def _q(i, parent=None, at=1, **x):
    return {"id": i, "parent": parent, "kind": "question", "title": i, "at": at, **x}


def _o(i, parent, at=1, **x):
    return {"id": i, "parent": parent, "kind": "option", "title": i, "at": at, **x}


def _n(i, parent=None, at=1, **x):
    return {"id": i, "parent": parent, "kind": "note", "title": i, "at": at, **x}


def test_a_question_with_an_answer_is_answered():
    nodes = [_q("q1", chosen="o1"), _o("o1", "q1")]
    assert question_state(nodes[0], nodes) == "answered"


def test_a_later_sibling_question_means_this_one_was_passed_over():
    nodes = [_n("r"), _q("q1", "r", at=1), _q("q2", "r", at=2)]
    assert question_state(nodes[1], nodes) == "passed"
    assert question_state(nodes[2], nodes) == "waiting"


def test_siblings_from_one_batch_are_parallel_questions_not_passed():
    # propose_nodes stamps ONE timestamp per batch, so equal `at` means the
    # agent asked both at once. Neither has been passed over.
    nodes = [_n("r"), _q("q1", "r", at=7), _q("q2", "r", at=7)]
    assert question_state(nodes[1], nodes) == "waiting"
    assert question_state(nodes[2], nodes) == "waiting"


def test_legacy_nodes_without_a_timestamp_are_never_marked_passed():
    nodes = [_n("r"), {"id": "q1", "parent": "r", "kind": "question", "title": "a"},
             {"id": "q2", "parent": "r", "kind": "question", "title": "b"}]
    assert question_state(nodes[1], nodes) == "waiting"


def test_a_question_locks_once_its_chosen_option_has_children():
    open_ = [_q("q1", chosen="o1"), _o("o1", "q1")]
    assert is_locked(open_[0], open_) is False
    grown = open_ + [_n("d1", "o1")]
    assert is_locked(grown[0], grown) is True


def test_the_chosen_option_is_the_row_right_after_its_question():
    nodes = [_q("q1", chosen="o2"), _o("o1", "q1"), _o("o2", "q1")]
    rows = spine_for(nodes)
    assert [(r["row"], r["node"]["id"]) for r in rows] == [
        ("question", "q1"), ("chosen", "o2")]
    assert [o["id"] for o in rows[0]["rejected"]] == ["o1"]
    assert rows[0]["options"] == []


def test_an_unanswered_question_shows_its_options_inline():
    nodes = [_q("q1"), _o("o1", "q1")]
    rows = spine_for(nodes)
    assert [o["id"] for o in rows[0]["options"]] == ["o1"]
    assert rows[0]["rejected"] == []


def test_progress_hung_off_the_question_still_reads_after_the_answer():
    # The legacy bridge. Every canvas written before this slice hangs its
    # progress off the QUESTION, not off the chosen option, and decision_tree
    # is append-only so it can never be corrected in place.
    nodes = [_q("q1", chosen="o1"), _o("o1", "q1"), _n("d1", "q1", at=2)]
    assert [r["node"]["id"] for r in spine_for(nodes)] == ["q1", "o1", "d1"]


def test_progress_hung_off_the_chosen_option_reads_the_same_way():
    nodes = [_q("q1", chosen="o1"), _o("o1", "q1"), _n("d1", "o1", at=2)]
    assert [r["node"]["id"] for r in spine_for(nodes)] == ["q1", "o1", "d1"]


def test_reparenting_moves_progress_under_the_chosen_option():
    # The map draws edges, so there the parent has to be literally right.
    nodes = [_q("q1", chosen="o1"), _o("o1", "q1"), _n("d1", "q1")]
    out = {n["id"]: n["parent"] for n in reparented(nodes)}
    assert out == {"q1": None, "o1": "q1", "d1": "o1"}


def test_reparenting_leaves_the_stored_nodes_untouched():
    nodes = [_q("q1", chosen="o1"), _o("o1", "q1"), _n("d1", "q1")]
    reparented(nodes)
    assert nodes[2]["parent"] == "q1"


def test_reparenting_does_nothing_to_an_unanswered_question():
    nodes = [_q("q1"), _o("o1", "q1"), _n("d1", "q1")]
    assert {n["id"]: n["parent"] for n in reparented(nodes)}["d1"] == "q1"
