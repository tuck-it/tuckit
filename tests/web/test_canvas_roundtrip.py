import json

import pytest
from django.urls import reverse

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice, propose_nodes
from tuckit.core.services.watches import open_watch, read_watch


def _tree(slice_):
    propose_nodes(slice_, [
        {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "Left"},
        {"id": "o2", "parent": "q1", "kind": "option", "title": "Right"},
    ])


@pytest.mark.django_db
def test_the_browser_door_retires_the_channel_too(client_local, org):
    """mutations.slice_edit and the MCP tool are two doors onto one service.
    Retiring watches in the tool instead of the service would leave a live
    channel behind for everyone who writes their spec in the browser."""
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    _tree(s)
    _, raw = open_watch(s)

    client_local.post(
        reverse("web:slice_edit", args=[org.slug, s.id]),
        {"spec": "## Decided\nWe went with Right."},
        HTTP_HX_REQUEST="true",
    )

    assert read_watch(raw) is None


@pytest.mark.django_db
def test_the_whole_loop_from_click_to_url(client_local, org):
    """Browser click -> POST -> decision_tree -> watch -> the URL a shell polls. Every
    piece is tested on its own; this is the only test that proves they are
    connected."""
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    _tree(s)
    _, raw = open_watch(s)

    client_local.post(
        reverse("web:slice_choice", args=[org.slug, s.id]), {"node_id": "o2"}
    )
    res = client_local.get(reverse("web:canvas_watch", args=[raw]))

    assert json.loads(res.content) == {"status": "chosen", "choice": "o2"}
