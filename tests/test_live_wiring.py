from pathlib import Path

import pytest
from django.urls import reverse
from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice

import tuckit.web


def _live_js():
    return (Path(tuckit.web.__file__).parent / "static/web/live.js").read_text()


@pytest.fixture
def member(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user(email="m@b.co", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    return org, user


@pytest.mark.django_db
def test_live_config_present_on_tenant_page(client, member):
    org, user = member
    create_area(org, "Backend")
    client.force_login(user)
    html = client.get(reverse("web:inbox", args=[org.slug])).content.decode()
    assert 'id="live-config"' in html
    assert f"/{org.slug}/live" in html
    assert 'data-cursor="' in html


@pytest.mark.django_db
def test_inbox_marks_main_live(client, member):
    org, user = member
    client.force_login(user)
    html = client.get(reverse("web:inbox", args=[org.slug])).content.decode()
    assert 'data-live-refresh="1"' in html


def test_heat_decays_from_the_seeded_timestamp():
    """Static assertion on purpose: a decay that silently never runs still
    renders a valid page and returns 200, so no endpoint test can see it."""
    js = (Path(tuckit.web.__file__).parent / "static/web/heat.js").read_text()
    js = " ".join(js.split())
    assert "data-last-touch" in js
    assert "--heat" in js


def test_the_old_ring_is_gone():
    """The ring and the warmth would be two languages for one idea."""
    css = (Path(tuckit.web.__file__).parent / "static/web/app.css").read_text()
    assert "just-live" not in css
    live_js = (Path(tuckit.web.__file__).parent / "static/web/live.js").read_text()
    assert "just-live" not in live_js


def test_live_refresh_morphs_instead_of_replacing():
    """Full replacement destroys every element, and a CSS transition only runs
    when a surviving element's value changes — so without morph no data change
    can ever animate."""
    js = " ".join(_live_js().split())
    assert '"morphStyle":"outerHTML"' in js


def test_live_refresh_preserves_the_active_control_value():
    """CRITICAL regression guard: the Inbox row's Area <select>
    (partials/_inbox_row.html) is a value-bearing control that lives inside
    the live morph target. Idiomorph re-syncs every <option selected> on each
    morph, which would reset that dropdown out from under the user mid-choice
    — so without ignoreActiveValue, any org activity firing a poll while a
    row's select is focused could silently discard the in-progress choice.

    ignoreActiveValue is far blunter than its name: idiomorph skips the WHOLE
    subtree of document.activeElement, not just a value. Hardcoding the flag
    would therefore freeze any focused element's subtree on every poll,
    including a <summary> or #main-content itself — so live.js decides it per
    swap in an htmx:beforeSwap listener, asking for the flag only when the
    currently focused element actually holds a value (INPUT / TEXTAREA /
    SELECT / contenteditable) before assigning Idiomorph.defaults.ignoreActiveValue.

    Not otherwise reachable from pytest: this is a DOM/morph interaction with
    no server-observable effect, so it is pinned here as a static assertion on
    the wiring actually present, in the style of the other tests in this
    file."""
    js = " ".join(_live_js().split())
    assert "htmx:beforeSwap" in js
    assert "Idiomorph.defaults.ignoreActiveValue" in js
    assert "document.activeElement" in js
    assert "isContentEditable" in js
    assert 'tagName === "INPUT"' in js
    assert 'tagName === "TEXTAREA"' in js
    assert 'tagName === "SELECT"' in js


def test_the_full_replace_workarounds_are_gone():
    """Both existed only because replacement threw the DOM away. Morph makes
    them dead code, and typingInMain actively froze the screen while typing."""
    js = _live_js()
    assert "typingInMain" not in js
    assert "window.scrollTo" not in js


def test_live_merges_the_canvas_instead_of_swapping_it():
    """Static assertion on purpose: a canvas that silently never updates still
    renders a valid page and returns 200, so no endpoint test can see it."""
    js = _live_js()
    assert "__canvas" in js
    assert "sync(" in js
    # Never assemble the path: every route is /<org>/-scoped and a hand-built
    # one 404s, which endpoint tests cannot catch.
    assert "location.pathname" in js


@pytest.mark.django_db
def test_the_slice_page_ships_the_poller_and_the_canvas(client, member):
    org, user = member
    a = create_area(org, "Backend")
    s = create_slice(org, area=a, title="Payments", spec="## Goal\ntext")
    client.force_login(user)

    html = client.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert 'id="live-config"' in html            # the poll the canvas rides
    assert "brainstorm.js" in html
    # The canvas owns its own DOM: a #main-content morph would replace the
    # cards mid-animation and lose the client's computed transforms.
    assert 'data-live-refresh="1"' not in html


def test_live_can_bring_a_canvas_into_existence():
    """The cold start: no canvas on the page yet, so there is no window.__canvas
    to gate on and no brainstorm.js loaded. Gating the merge on the API object
    alone is what made the first proposal invisible until F5."""
    js = _live_js()
    assert "data-graph-slot" in js
    assert "brainstorm.js" in js
