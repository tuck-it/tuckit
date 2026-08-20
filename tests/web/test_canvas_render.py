import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_every_heading_becomes_a_card(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Payments",
                     spec="## Goal\ntext\n\n### Detail\nmore")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-canvas" in body
    assert body.count('class="cnode') >= 3      # root + Goal + Detail
    assert 'data-parent=""' in body             # exactly one root


@pytest.mark.django_db
def test_the_canvas_stays_off_the_modal(client_local, org):
    # D15: the canvas needs a full page. The modal is a centred card and
    # cannot hold the tree.
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
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-canvas" in body
    assert 'class="spec-edit' in body       # the textarea is still there


@pytest.mark.django_db
def test_the_stage_starts_pending_so_nothing_flashes_unplaced(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Payments", spec="## Goal\ntext")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "data-pending" in body


@pytest.mark.django_db
def test_a_draft_renders_when_the_spec_is_empty(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Designing", spec="")
    s.draft = {"nodes": [
        {"id": "n1", "parent": None, "kind": "question",
         "title": "Which way?", "summary": "", "body": "", "at": 1787200000000},
        {"id": "n2", "parent": "n1", "kind": "option", "recommended": True,
         "title": "This way", "summary": "cheap", "body": "**because**"},
    ]}
    s.save(update_fields=["draft"])
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
