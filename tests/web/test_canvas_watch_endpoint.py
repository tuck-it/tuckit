import json

import pytest
from django.urls import reverse
from django.utils import timezone

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.watches import answer_watches, open_watch


@pytest.mark.django_db
def test_a_live_watch_says_it_is_waiting(client, org):
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    _, raw = open_watch(s)

    res = client.get(reverse("web:canvas_watch", args=[raw]))

    assert res.status_code == 200
    assert json.loads(res.content) == {"status": "waiting"}


@pytest.mark.django_db
def test_it_needs_no_login(client, org):
    """The whole point: the poll loop is a shell command with no credentials,
    and this exists so nobody is ever tempted to give it some."""
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    _, raw = open_watch(s)

    # `client` is anonymous; LoginRequiredMiddleware would 302 anything else.
    assert client.get(reverse("web:canvas_watch", args=[raw])).status_code == 200


@pytest.mark.django_db
def test_an_answer_comes_back_as_the_node_id(client, org):
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    _, raw = open_watch(s)
    answer_watches(s, "o2")

    res = client.get(reverse("web:canvas_watch", args=[raw]))

    assert json.loads(res.content) == {"status": "chosen", "choice": "o2"}


@pytest.mark.django_db
def test_it_leaks_nothing_about_the_slice(client, org):
    """Anyone who finds the URL sees this. Two keys, and the node id is a
    string the agent itself wrote."""
    a = create_area(org, "Secret Area")
    s = create_slice(org, area=a, title="Unreleased pricing work", spec="")
    # Node ids deliberately hold no digits: the leak check below matches
    # str(s.id) as a raw substring, and a digit-bearing node id (the bite's
    # original "o1") can coincidentally contain the slice's own small integer
    # id on a fresh sqlite test db (rowid 1) -- a false leak signal, not a
    # real one, since the returned node id is explicitly safe to echo back.
    s.decision_tree = {"nodes": [
        {"id": "q-charge", "parent": None, "kind": "question", "title": "Charge per seat?"},
        {"id": "o-yes", "parent": "q-charge", "kind": "option", "title": "Yes",
         "body": "internal reasoning nobody outside should read"},
    ]}
    s.save(update_fields=["decision_tree"])
    _, raw = open_watch(s)
    answer_watches(s, "o-yes")

    body = client.get(reverse("web:canvas_watch", args=[raw])).content.decode()

    assert set(json.loads(body)) == {"status", "choice"}
    for leak in ("Unreleased", "pricing", "Secret", "seat", "reasoning", org.slug, str(s.id)):
        assert leak not in body


@pytest.mark.django_db
def test_an_unknown_token_and_a_dead_one_answer_identically(client, org):
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    watch, raw = open_watch(s)
    watch.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    watch.save(update_fields=["expires_at"])

    dead = client.get(reverse("web:canvas_watch", args=[raw]))
    unknown = client.get(reverse("web:canvas_watch", args=["never-existed"]))

    assert dead.status_code == unknown.status_code == 404
    assert dead.content == unknown.content == b'{"status": "expired"}'


@pytest.mark.django_db
def test_reading_the_watch_costs_one_query(client, org, django_assert_num_queries):
    """Unauthenticated and polled every two seconds. It must never grow into a
    way to ask questions about a slice."""
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Canvas", spec="")
    _, raw = open_watch(s)

    with django_assert_num_queries(1):
        client.get(reverse("web:canvas_watch", args=[raw]))
