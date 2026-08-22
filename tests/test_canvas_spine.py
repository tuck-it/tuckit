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
    assert rows[0]["options"] == []
    assert [o["id"] for o in rows[1]["rejected"]] == ["o1"]


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


def test_a_sealed_record_asks_nobody_anything():
    """A question left unanswered when the spec was written is not your turn.

    Slice 208 is the real case: two of its questions have no answer AND no
    later sibling to mark them as passed over, because the design simply
    finished around them. Reading `waiting` off that would have the board
    claim someone's turn forever, on a record nothing can be written to.
    """
    nodes = [_q("q1"), _o("o1", "q1")]

    assert question_state(nodes[0], nodes, closed=True) == "passed"
    assert question_state(nodes[0], nodes) == "waiting"


def test_a_sealed_record_offers_no_options_to_pick_from():
    nodes = [_q("q1"), _o("o1", "q1")]

    row = spine_for(nodes, closed=True)[0]
    assert row["state"] == "passed"
    assert row["options"] == []
    assert [o["id"] for o in row["rejected"]] == ["o1"]


def test_the_rejected_fold_comes_after_the_winner_never_before_it():
    """Order is the whole argument of this view.

    A fold of losing options printed above the option that won reads as if the
    losers came first -- the exact ambiguity about "what did I actually pick"
    that this redesign exists to remove.
    """
    nodes = [_q("q1", chosen="o2"), _o("o1", "q1"), _o("o2", "q1")]
    rows = spine_for(nodes)

    assert rows[0]["rejected"] == []                       # not on the question
    assert [o["id"] for o in rows[1]["rejected"]] == ["o1"]  # on the winner


def test_a_legacy_canvas_locks_on_work_hung_off_the_question():
    """The lock has to see the continuation wherever its author put it.

    Reading only the chosen option's children means every canvas written
    before the parent rule -- which is every canvas that exists -- reports as
    unlocked no matter how much was built on the answer. That is the same
    blind spot the whole picture had, arriving through the back door.
    """
    legacy = [_q("q1", chosen="o1"), _o("o1", "q1"), _n("d1", "q1", at=2)]
    assert is_locked(legacy[0], legacy) is True

    modern = [_q("q1", chosen="o1"), _o("o1", "q1"), _n("d1", "o1", at=2)]
    assert is_locked(modern[0], modern) is True


def test_options_alone_do_not_lock_a_question():
    # Candidates are not work built on the answer; they are the answer's
    # alternatives, and a misclick has to stay correctable while that is all
    # there is.
    nodes = [_q("q1", chosen="o1"), _o("o1", "q1"), _o("o2", "q1")]
    assert is_locked(nodes[0], nodes) is False


def test_work_done_under_an_option_that_lost_is_not_dropped():
    """A branch explored and abandoned is the record, not noise.

    Walking only the winner's children made every node under a losing option
    vanish from the spine -- and since the map carries no bodies, their
    reasoning became unreachable on every surface. `propose` refuses to create
    these now, but the record is append-only and older canvases hold them.
    """
    nodes = [_q("q1", chosen="o1"), _o("o1", "q1"), _o("o2", "q1"),
             _n("d9", "o2", at=2), _q("q5", "d9", at=3)]

    rows = spine_for(nodes)
    lost = rows[1]["rejected"][0]

    assert lost["id"] == "o2"
    assert [r["node"]["id"] for r in lost["descendants"]] == ["d9", "q5"]


def test_an_option_that_lost_with_nothing_under_it_carries_an_empty_branch():
    nodes = [_q("q1", chosen="o1"), _o("o1", "q1"), _o("o2", "q1")]

    assert spine_for(nodes)[1]["rejected"][0]["descendants"] == []


def test_a_note_alongside_the_options_locks_the_first_answer_immediately():
    """The cost of the wider lock, stated plainly.

    The spec's table says the lock fires when the CHOSEN option has children.
    Counting the question's non-option children too is what makes the legacy
    shape lock at all -- but it also means an agent that parks a context note
    beside the options seals the very first pick, and a genuine misclick there
    is uncorrectable. Guard 1 refuses such a note on an ANSWERED question, so
    this only arises when the note lands before anyone picks.
    """
    nodes = [_q("q1", chosen="o1"), _o("o1", "q1"), _o("o2", "q1"),
             _n("context", "q1")]

    assert is_locked(nodes[0], nodes) is True
