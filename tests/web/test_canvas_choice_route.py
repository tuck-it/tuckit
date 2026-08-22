import pytest
from django.urls import reverse

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice, propose_nodes


def _tree(slice_):
    propose_nodes(slice_, [
        {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "Left"},
        {"id": "o2", "parent": "q1", "kind": "option", "title": "Right"},
    ])


@pytest.mark.django_db
def test_a_click_settles_the_question(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    _tree(s)

    res = client_local.post(
        reverse("web:slice_choice", args=[org.slug, s.id]), {"node_id": "o2"}
    )

    assert res.status_code == 204
    s.refresh_from_db()
    assert next(n for n in s.draft["nodes"] if n["id"] == "q1")["chosen"] == "o2"


@pytest.mark.django_db
def test_the_response_carries_the_live_cursor(client_local, org):
    """brainstorm.js posts with fetch(), which never fires the htmx event
    live.js normally adopts this from. Without the header there is nothing for
    it to adopt, and the click comes back two seconds later announced to the
    person who made it.
    """
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    _tree(s)

    res = client_local.post(
        reverse("web:slice_choice", args=[org.slug, s.id]), {"node_id": "o2"}
    )

    assert int(res["X-Live-Cursor"]) > 0


@pytest.mark.django_db
def test_a_bad_node_is_a_400_not_a_500(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    _tree(s)

    res = client_local.post(
        reverse("web:slice_choice", args=[org.slug, s.id]), {"node_id": "nope"}
    )

    assert res.status_code == 400


@pytest.mark.django_db
def test_a_get_is_refused(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    _tree(s)

    res = client_local.get(reverse("web:slice_choice", args=[org.slug, s.id]))

    assert res.status_code == 405


@pytest.mark.django_db
def test_a_stranger_cannot_choose(client, org):
    """Anonymous: LoginRequiredMiddleware redirects before the view runs. The
    canvas is a tenant surface and this endpoint writes.
    """
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    _tree(s)

    res = client.post(
        reverse("web:slice_choice", args=[org.slug, s.id]), {"node_id": "o2"}
    )

    assert res.status_code in (302, 404)
    s.refresh_from_db()
    assert "chosen" not in next(n for n in s.draft["nodes"] if n["id"] == "q1")
