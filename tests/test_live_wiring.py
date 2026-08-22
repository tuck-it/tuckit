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
    s = create_slice(org, area=a, title="Payments", spec="")
    s.decision_tree = {"nodes": [{"id": "n1", "parent": None, "kind": "question",
                                  "title": "Which way?", "summary": "", "body": ""}]}
    s.save(update_fields=["decision_tree"])
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


def test_the_canvas_can_be_maximized_and_refits():
    """Static assertions: a maximize that never refits still renders a valid
    page and returns 200 -- the tree would just sit in the old corner at the
    old scale, which no endpoint test can see."""
    web = Path(tuckit.web.__file__).parent
    js = (web / "static/web/brainstorm.js").read_text()
    css = (web / "static/web/app.css").read_text()

    assert "data-maximize" in js
    assert "is-max" in js and "is-max" in css
    assert "Escape" in js                      # a full-viewport overlay needs a way out
    assert ".canvas.is-max" in css


def test_the_canvas_posts_a_choice_and_skips_its_own_echo():
    """Static wiring guards. Two failures here are invisible to every endpoint
    test: an hx-post that never binds on a live-arrived card, and a fetch whose
    cursor is never adopted -- which makes your own click come back two seconds
    later announced as somebody else's, replacing your own toast."""
    from pathlib import Path
    import tuckit.web

    web = Path(tuckit.web.__file__).parent
    js = (web / "static/web/spine.js").read_text()
    graph = (web / "static/web/brainstorm.js").read_text()
    live = (web / "static/web/live.js").read_text()
    css = (web / "static/web/app.css").read_text()
    spine = (web / "templates/web/partials/_spine.html").read_text()
    canvas = (web / "templates/web/partials/_canvas.html").read_text()

    assert "data-pick" in js and "data-pick" in spine
    assert "choiceUrl" in js                     # read off the element, not built
    assert "hx-post" not in spine                # live-arrived rows are never processed
    assert "__liveAdoptCursor" in js and "__liveAdoptCursor" in live
    assert "X-Live-Cursor" in js
    assert "chose" in live                       # the verb has a label
    assert ".spine-pick" in css

    # Exactly one surface writes the choice. The map is a second opinion on
    # the record, never a second way to write it -- and a card title, which is
    # what you click to READ a node, must not be a control at all.
    assert "data-pick" not in canvas
    assert "data-pick" not in graph


def test_the_spine_has_a_live_path_and_binds_only_once():
    """Two failures no endpoint test can see.

    The spine carries the pick controls, so without a live path a question
    proposed mid-session is unanswerable until the human reloads -- the exact
    "the poll is 200 but the screen never grows" symptom, on the surface the
    whole design conversation runs through.

    And _spine.html renders INSIDE .detail-body, the hx-target of Reopen,
    Restore, Ship and every inline editor. htmx re-evaluates script tags in
    swapped content, so a spine.js without a sentinel would stack one more
    document listener per swap and turn one click into N irreversible POSTs.
    """
    from pathlib import Path
    import tuckit.web

    web = Path(tuckit.web.__file__).parent
    live = (web / "static/web/live.js").read_text()
    js = (web / "static/web/spine.js").read_text()
    css = (web / "static/web/app.css").read_text()
    detail = (web / "templates/web/partials/_slice_detail.html").read_text()

    assert "data-spine" in live                  # the poll refreshes it
    assert "__liveRefreshSpine" in live and "__liveRefreshSpine" in js
    assert "window.__spine" in js                # bind-once sentinel

    # The spine sits inside the swap target, which is why the sentinel matters.
    body_at = detail.index('class="detail-body')
    assert detail.index("_spine.html") > body_at

    # The map is closed by CSS, not by a script that has to run first.
    assert "[data-graph-slot] { display: none; }" in css
