import pytest
from django.urls import reverse

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice, propose_nodes


@pytest.mark.django_db
def test_editing_the_spec_in_the_browser_keeps_the_decision_record(client_local, org):
    """The web inline edit and the MCP tool are two doors onto one service. A
    fix applied to only one of them leaves the other silently broken."""
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    propose_nodes(s, [{"id": "n1", "parent": None, "kind": "question", "title": "Q"}])

    client_local.post(
        reverse("web:slice_edit", args=[org.slug, s.id]),
        {"spec": "## Decision\nWe went with A."},
        HTTP_HX_REQUEST="true",
    )

    s.refresh_from_db()
    assert s.spec.startswith("## Decision")
    assert [n["id"] for n in s.decision_tree["nodes"]] == ["n1"]


@pytest.mark.django_db
def test_the_canvas_keeps_drawing_the_same_record_after_a_spec_lands(client_local, org):
    """It used to swap source -- decision record while undesigned, the spec's
    headings afterwards. It no longer swaps, because the two are not two answers
    to one question: the record is how this was decided and it outlives the
    spec being written (TP-238)."""
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    propose_nodes(s, [{"id": "n1", "parent": None, "kind": "question", "title": "Q"}])

    before = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "data-canvas" in before and 'data-id="n1"' in before

    client_local.post(
        reverse("web:slice_edit", args=[org.slug, s.id]),
        {"spec": "## Goal\ntext\n\n### Detail\nmore"},
        HTTP_HX_REQUEST="true",
    )

    after = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "data-canvas" in after            # still there
    assert 'data-id="n1"' in after           # ...and it is still the SAME record
    # ...and only that record: the spec's headings are not drawn as cards. The
    # spec still renders in its own block on the page, which is not this.
    # 'class="cnode' alone also matches cnode-t/-s/-b inside a card, so count
    # the article's own class pair.
    assert after.count('class="cnode cnode--') == 1
