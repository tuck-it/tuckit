"""Guards for the defects found in the 2026-07-22 persona walkthrough.

Each test names the failure it prevents. They are deliberately assertions about
markup contracts (roles, element types, attributes) rather than about styling —
what broke before was always "this control exists but cannot be reached or
announced", which is a markup property.
"""
import re
from pathlib import Path

import pytest

from tuckit.core.services.areas import create_area, list_areas
from tuckit.core.services.plans import create_plan
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite
from tuckit.core.services.tickets import create_ticket

STATIC = Path(__file__).resolve().parents[2] / "tuckit" / "web" / "static" / "web"


def _p(org):
    return f"/{org.slug}"


# --- Keyboard reachability -------------------------------------------------

@pytest.mark.django_db
def test_board_cards_are_links_not_divs(client_local, org):
    """Board cards were <div hx-get>: no href, no tabindex, no role. The only
    tab stops inside <main> on the Board were the Board/List toggles, so a
    keyboard user could not open any slice at all (WCAG 2.1.1)."""
    area = create_area(org, "Backend")
    s = create_slice(area, "Retry webhooks", status="planned")
    body = client_local.get(f"{_p(org)}/roadmap/?view=board").content.decode()

    assert 'class="slice-card-link"' in body
    card = re.search(r'<a class="slice-card-link"[^>]*>', body).group(0)
    assert f"/slices/{s.id}/" in card, "the card must be a real navigable link"
    # The old markup: a div carrying the hx-get and nothing else.
    assert '<div class="slice-card" data-slice-id' in body, "drag target keeps the id"
    assert not re.search(r'<div class="slice-card"[^>]*hx-get', body), \
        "hx-get belongs on the anchor, not on a non-focusable div"


@pytest.mark.django_db
def test_slice_panel_edit_surfaces_are_buttons(client_local, org):
    """Title/spec/overview/constraints were <span>/<div> with x-on:click, so a
    keyboard user could Drop the slice and Delete its plan but could not edit
    any of its text — every destructive action reachable, no authoring one."""
    area = create_area(org, "Backend")
    s = create_slice(area, "Retry webhooks", spec="why")
    create_plan(s, title="v1", actor="human")
    body = client_local.get(f"{_p(org)}/slices/{s.id}/").content.decode()

    for label in ("Edit spec", "Edit plan overview", "Edit plan constraints"):
        assert re.search(rf'<button[^>]*aria-label="{label}"', body), f"{label} must be a button"
    assert re.search(r'<button[^>]*class="panel-title edit-surface"', body), \
        "the slice title must be focusable"
    assert not re.search(r'<span class="panel-title"[^>]*x-on:click', body)
    assert not re.search(r'<div class="spec"[^>]*x-on:click', body)


@pytest.mark.django_db
def test_bite_toggle_exposes_checkbox_state(client_local, org):
    """The toggle was <button aria-label="Toggle done"> with the state drawn
    only as a tick, so assistive tech could not tell done from not-done."""
    area = create_area(org, "Backend")
    s = create_slice(area, "Retry webhooks")
    plan = create_plan(s, title="v1", actor="human")
    create_bite(plan, "Write the test", source="human")
    body = client_local.get(f"{_p(org)}/slices/{s.id}/").content.decode()

    box = re.search(r'<button class="checkbox[^"]*"[^>]*>', body).group(0)
    assert 'role="checkbox"' in box
    assert 'aria-checked="false"' in box
    assert 'aria-label="Write the test"' in box, "name the bite, not the verb"


# --- Announcements ---------------------------------------------------------

@pytest.mark.django_db
def test_toast_is_a_live_region(client_local, org):
    """Every success/failure message was visual-only and vanished in 1.8s."""
    body = client_local.get(f"{_p(org)}/").content.decode()
    toast = re.search(r'<div id="toast"[^>]*>', body).group(0)
    assert 'role="status"' in toast
    assert 'aria-live="polite"' in toast


@pytest.mark.django_db
def test_skip_link_is_first_and_targets_main(client_local, org):
    """13 of 18 focusable elements on a page are sidebar chrome; without a skip
    link that nav is re-tabbed on every page."""
    body = client_local.get(f"{_p(org)}/").content.decode()
    assert '<a class="skip-link" href="#main-content">' in body
    assert 'id="main-content"' in body
    assert body.index("skip-link") < body.index('class="topbar-mobile"'), \
        "the skip link must come before any other focusable content"


@pytest.mark.django_db
def test_icons_are_hidden_from_assistive_tech(client_local, org):
    """Decorative SVGs were exposed, doubling every labelled control."""
    body = client_local.get(f"{_p(org)}/").content.decode()
    svgs = re.findall(r"<svg[^>]*>", body)
    assert svgs, "sanity: the page renders icons"
    assert all('aria-hidden="true"' in tag for tag in svgs)


# --- Dialogs ---------------------------------------------------------------

@pytest.mark.django_db
def test_capture_overlays_are_real_dialogs(client_local, org):
    """The .capture-overlay family (quick capture, new slice, new area) had no
    role, no aria-modal and no focus trap, so four Tabs from an open capture
    dialog landed on a control behind the scrim."""
    create_area(org, "Backend")
    body = client_local.get(f"{_p(org)}/").content.decode()
    overlays = re.findall(r'<div class="capture-overlay"[^>]*>', body, re.S)
    assert overlays, "sanity: at least the quick-capture overlay renders"
    for tag in overlays:
        assert 'role="dialog"' in tag
        assert 'aria-modal="true"' in tag
        assert "trapOverlay" in tag, "Tab must not escape an open dialog"
        assert "dialogSync" in tag, "focus must return to the opener on close"


@pytest.mark.django_db
def test_dialogs_focus_themselves_without_a_cross_scope_ref(client_local, org):
    """Opening quick capture left the caret on the trigger and anything typed
    went nowhere: the triggers called `$refs.captureInput.focus()` from the
    <body> scope, but that ref registers inside the form's own x-data and
    Alpine's $refs only walks UP. dialogSync now focuses the dialog's first
    field itself, and the dead ref calls are gone."""
    body = client_local.get(f"{_p(org)}/").content.decode()
    # Only handler attributes matter here; base.html explains the old bug in a
    # comment, and matching that would make this test pass for the wrong reason.
    handlers = re.findall(r'x-on:[^=]+="[^"]*"', body)
    offenders = [h for h in handlers if "$refs.captureInput" in h]
    assert not offenders, f"cross-scope ref never resolved: {offenders}"
    assert "dialogSync" in body, "dialogs must focus themselves"
    # setTimeout, not rAF: rAF is paused in a background tab, which would leave
    # a dialog open with focus stranded outside it.
    dialog_sync_src = body.split("function dialogSync")[1][:1200]
    # Match the call site, not the comment that explains why it is not used.
    assert "requestAnimationFrame(" not in dialog_sync_src
    assert "setTimeout(" in dialog_sync_src


# --- Destructive / one-way actions -----------------------------------------

@pytest.mark.django_db
def test_inbox_row_does_not_auto_promote(client_local, org):
    """Changing the Area select alone used to promote the ticket immediately.
    promote_ticket() ends a ticket's lifecycle and reopen_ticket() refuses
    promoted tickets, so a stray dropdown change was unrecoverable."""
    create_area(org, "Backend")
    create_ticket(org, "Invoice PDF is blank", source="human")
    body = client_local.get(f"{_p(org)}/inbox/").content.decode()

    row = re.search(r'<div class="ticket-row"[^>]*>', body).group(0)
    assert 'hx-trigger="change"' not in row, "a select change must not mutate anything"
    assert "<form class=\"ticket-row\"" not in body, "the row must not be a self-submitting form"
    assert ">Promote</button>" in body, "promotion needs an explicit control"
    assert ":disabled=\"!area\"" in body, "and it stays disabled until an area is chosen"
    assert "cannot be undone" in body, "the confirm must say the action is one-way"


@pytest.mark.django_db
def test_area_delete_confirm_counts_what_it_destroys(client_local, org):
    """The old confirm said "and all items in it" without the one number that
    decides whether you click OK. Dropped slices are excluded so this agrees
    with the count the Areas overview shows."""
    area = create_area(org, "Backend")
    create_slice(area, "One", status="planned")
    create_slice(area, "Two", status="planned")
    create_slice(area, "Old", status="dropped")
    body = client_local.get(f"{_p(org)}/").content.decode()
    assert "and its 2 slices? This cannot be undone." in body


# --- Drag alternatives (WCAG 2.5.7) ----------------------------------------

@pytest.mark.django_db
def test_board_offers_a_non_drag_status_move(client_local, org):
    area = create_area(org, "Backend")
    create_slice(area, "Retry webhooks", status="building")
    body = client_local.get(f"{_p(org)}/roadmap/?view=board").content.decode()
    assert 'aria-label="Move Retry webhooks to planned"' in body
    assert 'aria-label="Move Retry webhooks to shipped"' in body


@pytest.mark.django_db
def test_area_move_reorders_without_dragging(client_local, org):
    first = create_area(org, "Alpha")
    second = create_area(org, "Beta")
    assert [a.id for a in list_areas(org)] == [first.id, second.id]

    resp = client_local.post(f"{_p(org)}/areas/{second.id}/move", {"direction": "up"})
    assert resp.status_code == 200
    assert [a.id for a in list_areas(org)] == [second.id, first.id]

    resp = client_local.post(f"{_p(org)}/areas/{second.id}/move", {"direction": "down"})
    assert resp.status_code == 200
    assert [a.id for a in list_areas(org)] == [first.id, second.id]


@pytest.mark.django_db
def test_area_move_refuses_past_the_ends_with_a_readable_reason(client_local, org):
    only = create_area(org, "Alpha")
    resp = client_local.post(f"{_p(org)}/areas/{only.id}/move", {"direction": "up"})
    assert resp.status_code == 400
    # The global htmx error handler shows this text verbatim, so it must read
    # as a sentence rather than a code.
    assert resp.content.decode() == "That area is already first."


@pytest.mark.django_db
def test_area_move_rejects_a_bogus_direction(client_local, org):
    area = create_area(org, "Alpha")
    resp = client_local.post(f"{_p(org)}/areas/{area.id}/move", {"direction": "sideways"})
    assert resp.status_code == 400


# --- Contrast tokens -------------------------------------------------------

def _luminance(hex_colour):
    h = hex_colour.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _light_tokens():
    css = (STATIC / "tokens.brand.css").read_text(encoding="utf-8")
    light = css[: css.index("@media (prefers-color-scheme: dark)")]
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-f]{6});", light))


def test_muted_body_text_meets_aa_on_every_light_surface():
    """--ink-faint is the product's entire secondary text tier (~106 uses). At
    #777d7e it was 3.35-4.01:1 on the four paper surfaces — below AA everywhere,
    and used at 11-13px so the large-text exemption never applied."""
    t = _light_tokens()
    for surface in ("paper", "paper-solid", "paper-raised", "paper-deep"):
        ratio = _contrast(t["ink-faint"], t[surface])
        assert ratio >= 4.5, f"--ink-faint on --{surface} is {ratio:.2f}:1"


def test_warning_text_meets_aa_on_light_surfaces():
    """--warn carries Drop slice, danger buttons and attention reasons — the
    highest-stakes copy was the least legible at 4.10:1."""
    t = _light_tokens()
    for surface in ("paper", "paper-solid", "paper-raised"):
        ratio = _contrast(t["warn"], t[surface])
        assert ratio >= 4.5, f"--warn on --{surface} is {ratio:.2f}:1"


def test_control_borders_have_a_dedicated_token_meeting_3to1():
    """--line is a decorative hairline (1.30:1) and was also drawing input
    boundaries, which 1.4.11 requires to be 3:1. Controls use --line-control."""
    product = (STATIC / "tokens.product.css").read_text(encoding="utf-8")
    assert "--line-control" in product
    light = product[: product.index("@media (prefers-color-scheme: dark)")]
    control = re.search(r"--line-control:\s*(#[0-9a-f]{6})", light).group(1)
    brand = _light_tokens()
    for surface in ("paper", "paper-raised", "paper-deep"):
        ratio = _contrast(control, brand[surface])
        assert ratio >= 3.0, f"--line-control on --{surface} is {ratio:.2f}:1"


def test_form_controls_keep_a_visible_focus_ring():
    """base.css replaced the focus outline with a border-colour swap, and
    app.css stripped `outline` on 16 more selectors — including .cmdk-input,
    which had no replacement at all."""
    base = (STATIC / "base.css").read_text(encoding="utf-8")
    app = (STATIC / "app.css").read_text(encoding="utf-8")
    assert "outline: none" not in base
    assert "outline: none" not in app, "a focus indicator must never be removed outright"
    assert "input:focus-visible" in base and "outline: 2px solid var(--blue)" in base


# --- Feedback that can actually be seen ------------------------------------

def test_toast_outranks_every_overlay():
    """The toast sat at z-index 50 while overlays are 60 and the capture dialog
    is 70. Both are body-level siblings, so an error raised from inside a modal
    rendered behind that modal's scrim: the silent failure the toast exists to
    end survived in exactly the place it mattered (WCAG 4.1.3)."""
    app = (STATIC / "app.css").read_text(encoding="utf-8")
    toast = re.search(r"\.toast\s*\{(.*?)\}", app, re.S).group(1)
    toast_z = int(re.search(r"z-index:\s*(\d+)", toast).group(1))

    others = [int(m) for m in re.findall(r"z-index:\s*(\d+)", app)]
    others.remove(toast_z)
    assert toast_z > max(others), (
        f"toast is z-{toast_z} but something else reaches z-{max(others)}"
    )


def test_disabled_buttons_do_not_look_enabled():
    """Promote is disabled until an area is chosen, and Save until the
    description changes. With no :disabled rule anywhere in the stylesheets
    both were pixel-identical to a live button, so they read as broken rather
    than as waiting for input."""
    base = (STATIC / "base.css").read_text(encoding="utf-8")
    app = (STATIC / "app.css").read_text(encoding="utf-8")
    assert ".button:disabled" in base, "the .button primitive needs a disabled state"
    assert ".btn:disabled" in app, "the settings .btn needs one too"


@pytest.mark.django_db
def test_org_description_has_an_explicit_save(client_local, org):
    """The description textarea saved on blur with no button and no success
    message, so the only way to learn whether it had stored was to reload
    (Nielsen 1). A failed save also reverted what had been typed."""
    body = client_local.get(f"{_p(org)}/settings/general").content.decode()
    row = body[body.index('aria-label="Organization description"'):]

    assert "hx-trigger=\"blur\"" not in row, "blur must not be the only way to save"
    assert "showToast('Saved.', 'ok')" in row, "a successful save must say so"
    # The old handler did `description = savedDescription` on failure.
    assert "description=savedDescription" not in row, \
        "a failed save must keep what the user typed"

@pytest.mark.django_db
def test_org_general_never_reads_alpine_state_from_htmx_attributes(client_local, org):
    """htmx evaluates hx-vals="js:{…}" and hx-on:: in the global scope, where
    an x-data name does not exist. Both fields here referenced `description`
    that way, so every save threw "description is not defined" before the
    request was built: the org name silently posted nothing, and the
    description's own success bookkeeping and error toast never ran.

    This is the same shape as the Alpine $refs bug in the walkthrough — an
    expression that looks scoped, resolves to nothing, and fails silently."""
    body = client_local.get(f"{_p(org)}/settings/general").content.decode()
    start = body.index('class="group settings-section"')
    section = body[start:body.index("</section>", start)]

    assert "hx-vals=\"js:" not in section, \
        "htmx cannot see x-data; send the real fields with hx-include instead"
    assert "hx-on::" not in section, \
        "use x-on:htmx:… so the handler runs inside the Alpine scope"
    assert 'hx-include="closest .settings-section"' in section, \
        "the description save must carry the name, which rename_org requires"
