import pytest

from django.conf import settings

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


def _app_css():
    from pathlib import Path

    import tuckit.web

    return (Path(tuckit.web.__file__).parent / "static/web/app.css").read_text()


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
    # The record renders as a document: no stage element, nothing to measure,
    # place, zoom or fit inside it.
    s = _slice_with(org, ANSWERED)
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    spine = body.split("data-spine", 1)[1].split("</section>", 1)[0]

    assert "data-spine" in body
    assert "data-stage" not in spine
    assert "data-canvas" not in spine


@pytest.mark.django_db
def test_the_record_now_reaches_the_modal(client_local, org):
    # TP-259. The record was kept off the modal because a STAGE does not fit a
    # centred card. A document does, and the record no longer needs the stage
    # to be readable.
    s = _slice_with(org, ANSWERED)
    body = client_local.get(
        f"/{org.slug}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true"
    ).content.decode()

    assert "data-spine" in body
    assert "WHY-IT-WON" in body


@pytest.mark.django_db
def test_the_modal_still_gets_no_stage(client_local, org):
    s = _slice_with(org, ANSWERED)
    body = client_local.get(
        f"/{org.slug}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true"
    ).content.decode()

    assert "data-canvas" not in body


@pytest.mark.django_db
def test_the_full_page_offers_the_map_as_a_toggle_and_opens_on_the_spine(client_local, org):
    s = _slice_with(org, ANSWERED)
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert 'data-view-toggle aria-pressed="false"' in body
    # Closed by default in CSS, not by a script that has to run first --
    # otherwise a slow load paints the map and runs a measure pass nobody
    # asked for.
    assert "[data-graph-slot] { display: none; }" in (
        (settings.BASE_DIR / "tuckit/web/static/web/app.css").read_text()
        if hasattr(settings, "BASE_DIR") else _app_css())


@pytest.mark.django_db
def test_a_modal_offers_no_map_toggle_because_it_has_no_map(client_local, org):
    s = _slice_with(org, ANSWERED)
    body = client_local.get(
        f"/{org.slug}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true"
    ).content.decode()

    assert "data-view-toggle" not in body


@pytest.mark.django_db
def test_an_abandoned_branch_survives_inside_the_fold(client_local, org):
    # The map carries no bodies any more, so if the spine drops what was built
    # under a losing option that reasoning is unreachable everywhere.
    s = _slice_with(org, ANSWERED + [
        {"id": "d9", "parent": "o2", "kind": "note", "title": "went-this-way",
         "body": "ABANDONED-REASONING", "at": 2}])
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "ABANDONED-REASONING" in body
    assert "went-this-way" in body
