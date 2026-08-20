import pytest
from django.urls import reverse

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice, propose_nodes


@pytest.mark.django_db
def test_editing_the_spec_in_the_browser_retires_the_canvas(client_local, org):
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
    assert s.draft == {}


@pytest.mark.django_db
def test_the_canvas_switches_source_rather_than_disappearing(client_local, org):
    """D14: the canvas is visible in every state; only its source changes."""
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
    assert 'data-id="n1"' not in after       # draft is gone
    assert after.count('class="cnode') >= 3  # root + Goal + Detail, from the spec
