import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


def _slice_with(org, nodes, spec=""):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Canvas", spec=spec)
    s.decision_tree = {"nodes": nodes}
    s.save(update_fields=["decision_tree"])
    return s


ANSWERED = [
    {"id": "q1", "parent": None, "kind": "question", "title": "Where?",
     "chosen": "o1", "at": 1},
    {"id": "o1", "parent": "q1", "kind": "option", "title": "A note",
     "summary": "no new channel", "body": "WHY-IT-WON", "at": 1},
    {"id": "o2", "parent": "q1", "kind": "option", "title": "Email",
     "summary": "loud", "body": "WHY-IT-LOST", "recommended": True, "at": 1},
]


@pytest.mark.django_db
def test_a_rejected_option_is_folded_but_still_in_the_dom(client_local, org):
    # The old canvas used display:none, while the CSS comment above it claimed
    # "why did that lose is still one click away" -- and no such click existed.
    # Folded means <details>, not deleted.
    s = _slice_with(org, ANSWERED)
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "WHY-IT-LOST" in body
    assert "<details" in body


@pytest.mark.django_db
def test_the_chosen_option_reads_in_full_right_after_its_question(client_local, org):
    s = _slice_with(org, ANSWERED)
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "WHY-IT-WON" in body
    assert body.index("Where?") < body.index("WHY-IT-WON")


@pytest.mark.django_db
def test_the_recommendation_disappears_once_the_question_is_answered(client_local, org):
    # Blue means one thing: the human's decision. An agent's preference that
    # survives the answer is what made four cards look chosen at once.
    s = _slice_with(org, ANSWERED)
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "spine-rec" not in body


@pytest.mark.django_db
def test_an_open_question_offers_a_pick_control_that_is_not_the_title(client_local, org):
    s = _slice_with(org, [
        {"id": "q1", "parent": None, "kind": "question", "title": "Where?", "at": 1},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "A note", "at": 1},
    ])
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    # The control is a button of its own, labelled for what it does. The
    # heading must not BE the button: clicking a title to read it is the most
    # natural gesture there is, and it used to record an irreversible choice.
    assert 'data-pick data-id="o1">Choose this</button>' in body


@pytest.mark.django_db
def test_a_locked_question_offers_no_pick_control_at_all(client_local, org):
    s = _slice_with(org, ANSWERED + [
        {"id": "d1", "parent": "o1", "kind": "note", "title": "Because", "at": 2}])
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-pick" not in body


@pytest.mark.django_db
def test_a_question_the_conversation_moved_past_stops_asking(client_local, org):
    s = _slice_with(org, [
        {"id": "r", "parent": None, "kind": "note", "title": "Problem", "at": 1},
        {"id": "q1", "parent": "r", "kind": "question", "title": "OLD-Q", "at": 1},
        {"id": "q2", "parent": "r", "kind": "question", "title": "NEW-Q", "at": 2},
    ])
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "OLD-Q" in body                      # still on the record
    assert body.count("is-waiting") == 1        # only NEW-Q asks


@pytest.mark.django_db
def test_the_spine_is_not_a_stage(client_local, org):
    s = _slice_with(org, ANSWERED)
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-spine" in body
