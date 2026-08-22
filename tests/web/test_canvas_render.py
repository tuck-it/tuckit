import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_the_canvas_stays_off_the_modal(client_local, org):
    # D15, still true of the STAGE: it needs a full page, and the modal is
    # a centred card. What changed with the spine is that the record no
    # longer needs the stage to be readable, so the modal does get it --
    # see test_the_record_now_reaches_the_modal (TP-259).
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Payments", spec="## Goal\ntext")
    body = client_local.get(
        f"/{org.slug}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true"
    ).content.decode()

    assert "data-canvas" not in body


@pytest.mark.django_db
def test_a_slice_with_nothing_to_draw_renders_no_canvas(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Empty", spec="")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-canvas" not in body


@pytest.mark.django_db
def test_the_spec_block_survives_next_to_the_canvas(client_local, org):
    # Regression guard: the spec block is inline-editable. The canvas is an
    # addition, never a replacement.
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Payments", spec="## Goal\ntext")
    s.decision_tree = {"nodes": [{"id": "n1", "parent": None, "kind": "question",
                                  "title": "Which way?", "summary": "", "body": ""}]}
    s.save(update_fields=["decision_tree"])
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-canvas" in body
    assert 'class="spec-edit' in body       # the textarea is still there
    assert 'data-id="n1"' in body           # spec and record coexist (TP-238)


@pytest.mark.django_db
def test_the_stage_starts_pending_so_nothing_flashes_unplaced(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Payments", spec="")
    s.decision_tree = {"nodes": [{"id": "n1", "parent": None, "kind": "question",
                                  "title": "Which way?", "summary": "", "body": ""}]}
    s.save(update_fields=["decision_tree"])
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-pending" in body


@pytest.mark.django_db
def test_a_decision_tree_renders_when_the_spec_is_empty(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Designing", spec="")
    s.decision_tree = {"nodes": [
        {"id": "n1", "parent": None, "kind": "question",
         "title": "Which way?", "summary": "", "body": "", "at": 1787200000000},
        {"id": "n2", "parent": "n1", "kind": "option", "recommended": True,
         "title": "This way", "summary": "cheap", "body": "**because**"},
    ]}
    s.save(update_fields=["decision_tree"])
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert 'data-id="n2"' in body
    assert 'data-parent="n1"' in body
    assert "is-rec" in body                  # the recommendation is marked
    assert "<strong>because</strong>" in body  # body goes through the shared renderer


@pytest.mark.django_db
def test_an_empty_slice_still_offers_a_slot_for_the_canvas(client_local, org):
    """The canvas is born mid-session: an agent proposes onto a slice that had
    nothing to draw. Without a slot on the page there is nowhere to put it and
    nothing to load brainstorm.js, so the first proposal needs a reload."""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Empty", spec="")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-graph-slot" in body
    assert "data-canvas" not in body      # the slot is empty: no stage yet


@pytest.mark.django_db
def test_the_modal_gets_no_slot_either(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Empty", spec="")
    body = client_local.get(
        f"/{org.slug}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true"
    ).content.decode()

    assert "data-graph-slot" not in body


@pytest.mark.django_db
def test_the_canvas_offers_a_maximize_control(client_local, org):
    """The stage is 60vh inside a content column. A tree three columns deep is
    1116px wide before any margin, so the surface built for comparing options
    pushes the options off it."""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Payments", spec="")
    s.decision_tree = {"nodes": [{"id": "n1", "parent": None, "kind": "question",
                                  "title": "Which way?", "summary": "", "body": ""}]}
    s.save(update_fields=["decision_tree"])
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-maximize" in body
    assert 'aria-expanded="false"' in body


@pytest.mark.django_db
def test_an_option_card_carries_a_pick_control(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Designing", spec="")
    s.decision_tree = {"nodes": [
        {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "Left"},
    ]}
    s.save(update_fields=["decision_tree"])
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-pick" in body
    # The address is rendered, never assembled in JS: these routes are
    # org-scoped and a hand-built path 404s where no test can see it.
    assert f"/{org.slug}/slices/{s.id}/choice" in body




@pytest.mark.django_db
def test_a_closed_record_offers_nothing_to_pick(client_local, org):
    """Once the spec is written the record stops accepting writes, so a pick
    control on it can only ever produce a 400 and a failure toast. It used to be
    unreachable because the record was deleted at that point; keeping the record
    is what made this state possible.
    """
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Decided", spec="## Decision\nA.")
    s.decision_tree = {"nodes": [
        {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "Left"},
    ]}
    s.save(update_fields=["decision_tree"])

    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert 'data-id="o1"' in body      # the record is still drawn...
    assert "data-pick" not in body     # ...but it is read-only


@pytest.mark.django_db
def test_an_open_record_still_offers_a_pick(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Designing", spec="")
    s.decision_tree = {"nodes": [
        {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "Left"},
    ]}
    s.save(update_fields=["decision_tree"])

    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-pick" in body


# ---- the map is a map, not a document ------------------------------------

STRAY = [
    {"id": "q1", "parent": None, "kind": "question", "title": "Where?",
     "chosen": "o1", "at": 1},
    {"id": "o1", "parent": "q1", "kind": "option", "title": "A note",
     "summary": "short", "body": "LONG-REASONING", "at": 1},
    {"id": "o2", "parent": "q1", "kind": "option", "title": "Email",
     "recommended": True, "at": 1},
    {"id": "d1", "parent": "q1", "kind": "note", "title": "Because", "at": 2},
]


def _drawn(client_local, org, nodes):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Canvas", spec="")
    s.decision_tree = {"nodes": nodes}
    s.save(update_fields=["decision_tree"])
    return client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()


@pytest.mark.django_db
def test_the_edge_runs_through_the_winner_not_past_it(client_local, org):
    # The complaint this slice exists for: the chosen card was a leaf and the
    # story continued from a sibling note, so "drill down from what I picked"
    # was structurally impossible. The record is append-only, so the fix is a
    # display-time re-parent.
    body = _drawn(client_local, org, STRAY)

    assert 'data-id="d1"' in body and 'data-parent="o1"' in body
    assert 'data-parent="q1"' in body          # the options still hang off q1


@pytest.mark.django_db
def test_a_map_card_carries_no_body(client_local, org):
    # A card with prose in it is not a node; it is a document at 25% zoom.
    stage = _drawn(client_local, org, STRAY).split("data-canvas", 1)[1]

    assert "LONG-REASONING" not in stage
    assert "cnode-b" not in stage


@pytest.mark.django_db
def test_the_reasoning_is_still_on_the_page_in_the_spine(client_local, org):
    # Dropping it from the card must not drop it from the screen.
    assert "LONG-REASONING" in _drawn(client_local, org, STRAY)
