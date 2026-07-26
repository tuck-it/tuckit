from pathlib import Path

import pytest
from django.urls import reverse
from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area

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
    """CRITICAL regression guard: the Inbox ticket rows' Area <select>
    (partials/_ticket_row.html) is a value-bearing control that lives inside
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


def test_ticket_row_area_select_resyncs_alpine_after_refresh():
    """IMPORTANT regression guard: idiomorph re-syncs each <option selected>
    during a morph, which can force an Inbox row's Area <select> back to its
    unselected placeholder — but Alpine's `area` value (driving the Promote
    button's :disabled) is a separate piece of state that morph never touches
    (it fires no input/change events). Left alone the two disagree: Alpine
    still thinks an area is chosen and leaves Promote enabled while the DOM
    would submit area_id="".

    Not reachable from pytest: this is a client-side Alpine+DOM interaction
    with no server-observable effect (the Django test client never runs
    Alpine or idiomorph), so — as with the other JS-only behaviors in this
    file — it is pinned as a static assertion on the resync wiring actually
    present in heat.js, not asserted end-to-end."""
    js = (Path(tuckit.web.__file__).parent / "static/web/heat.js").read_text()
    js = " ".join(js.split())
    assert "tuckit:live-refreshed" in js
    assert "area_id" in js
    assert "_x_dataStack" in js


def test_the_full_replace_workarounds_are_gone():
    """Both existed only because replacement threw the DOM away. Morph makes
    them dead code, and typingInMain actively froze the screen while typing."""
    js = _live_js()
    assert "typingInMain" not in js
    assert "window.scrollTo" not in js
