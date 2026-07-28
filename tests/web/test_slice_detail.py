import re

import pytest
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite


@pytest.mark.django_db
def test_slice_full_page_renders_spec_and_bites(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Payment integration", spec="## Goal\nWire up Stripe", status="open")
    create_bite(s, "SDK integration", status="done")
    resp = client_local.get(f"{p}/slices/{s.id}/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Payment integration" in body
    assert "<h2" in body            # markdown rendered
    assert "SDK integration" in body


@pytest.mark.django_db
def test_slice_detail_is_partial(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="X")
    resp = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    assert "<!doctype html>" not in body.lower()   # partial, not full page
    assert "X" in body


@pytest.mark.django_db
def test_spec_html_is_sanitized(client_local, org):
    p = f"/{org.slug}"
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Risky spec", spec="## Title\n<script>alert(1)</script>\n<img src=x onerror=alert(1)>")
    resp = client_local.get(f"{p}/slices/{s.id}/")
    body = resp.content.decode()
    assert resp.status_code == 200
    # Scope assertions to the rendered spec_html output (the `spec` div).
    # base.html legitimately ships vendor <script> tags, and the edit form
    # intentionally shows the raw (auto-escaped) spec text in a <textarea>
    # for editing, so checking the whole page would collide with both.
    spec_section = re.search(r'<button[^>]*class="spec[^"]*".*?</button>', body, re.S).group(0)
    assert "<script>" not in spec_section
    assert "onerror" not in spec_section
    assert "<h2" in spec_section


@pytest.mark.django_db
def test_slice_other_workspace_404(client_local, org):
    from tuckit.core.models import Org
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    s = create_slice(other_org, area=create_area(other_org, "A"), title="secret")
    assert client_local.get(f"{p}/slices/{s.id}/").status_code == 404


@pytest.mark.django_db
def test_slice_detail_shows_its_activity_thread(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice, set_slice_status
    from tuckit.core.services.bites import create_bite
    p = f"/{org.slug}"
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Thread slice", status="open")       # logs created (slice)
    set_slice_status(s, "shipped")                            # logs status_changed (slice)
    create_bite(s, "First bite")                              # logs created (bite)
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="slice-activity"' in body                  # thread section present
    assert body.count('class="activity-row"') >= 3           # slice + status + bite events
    assert "First bite" in body                              # bite event joined into the slice thread


@pytest.mark.django_db
def test_slice_detail_context_flags_and_progress(org):
    from tuckit.web.detail import slice_detail_context
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    s = create_slice(org, area=create_area(org, "Design"), title="T")
    create_bite(s, "a", status="done")
    create_bite(s, "b")  # 1 of 2 done -> 50%

    panel = slice_detail_context(s, is_modal=True)
    assert panel["is_modal"] is True
    assert panel["modal_qs"] == "?modal=1"
    assert (panel["bites_done"], panel["bites_total"], panel["bites_pct"]) == (1, 2, 50)

    page = slice_detail_context(s)  # default is_modal=False
    assert page["is_modal"] is False
    assert page["modal_qs"] == ""


@pytest.mark.django_db
def test_panel_header_title_and_stage_pill(client_local, org):
    """The old status dropdown (status-menu/status-opt) is gone: stage is a
    read-only pill (A0 — nothing left to pick)."""
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    s = create_slice(a.org, area=a, title="Dark mode policy", status="open")

    # panel context
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="area-chip"' in body
    assert f'href="/{org.slug}/areas/{a.slug}/"' in body   # chip links to area
    assert "Design" in body
    assert 'class="props"' in body
    assert 'class="status-pill status-pill--static"' in body   # read-only stage pill
    assert "status-opt" not in body                             # no status-picking menu
    assert "Created" in body and "Updated" in body        # properties rows
    assert 'class="section-label">Spec' in body          # spec is a labeled section
    # panel-only chrome present
    assert "crumb-close" in body
    assert "Open full page" in body


@pytest.mark.django_db
def test_full_page_hides_panel_only_chrome(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    s = create_slice(a.org, area=a, title="Full page")
    body = client_local.get(f"{p}/slices/{s.id}/").content.decode()   # full page, no modal=1
    assert "crumb-close" not in body        # no close button on the full page
    assert "Open full page" not in body     # no self-link on the full page
    assert 'class="area-chip"' in body     # breadcrumb chip still shown on full page


@pytest.mark.django_db
def test_steps_progress_and_empty_state(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    p = f"/{org.slug}"
    a = create_area(org, "Design")
    s = create_slice(a.org, area=a, title="S")

    # empty: the Steps empty-state is shown, and no progress bar
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert "No steps yet" in body
    assert 'class="row-prog-track"' not in body   # no progress bar when there are no bites

    # with bites: count + progress shown, empty state gone, AND the bites
    # actually render as rows (not just the header count). Bites hang off the
    # Slice now, so there is no plan to nest them under and no way for the
    # header count and the list underneath it to disagree.
    create_bite(s, "a", status="done")
    create_bite(s, "b")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert "No steps yet" not in body
    assert "1/2" in body
    assert 'class="row-prog-track"' in body
    assert "width: 50%" in body
    assert 'aria-label="a"' in body   # bite row actually rendered, not just counted
    assert 'aria-label="b"' in body


@pytest.mark.django_db
def test_action_bar_has_copy_and_drop(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Design"), title="Action", status="open")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="action-bar"' in body
    assert "Copy link" in body
    assert "Drop slice" in body


@pytest.mark.django_db
def test_tags_live_in_properties_not_a_context_section(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Design"), title="Tag")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="section-label">Context' not in body   # standalone Context section removed
    assert '<span class="prop-key">Tags' in body          # tags now a property row
    assert "Add tag" in body
    assert "meta-area" not in body


@pytest.mark.django_db
def test_activity_timeline_has_nodes(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice, set_slice_status
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Design"), title="Timeline", status="open")
    set_slice_status(s, "shipped")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="timeline"' in body
    assert 'class="tl-node"' in body      # a node marker per activity row


@pytest.mark.django_db
def test_slice_activity_helper_is_chronological_and_scoped(org):
    from tuckit.core.services.activity import slice_activity
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice, set_slice_status
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="A", status="open")
    set_slice_status(s, "shipped")
    other = create_slice(a.org, area=a, title="B", status="open")                 # unrelated slice's events excluded
    events = slice_activity(s)
    times = [e.created_at for e in events]
    assert times == sorted(times) and len(events) >= 2        # oldest-first
    assert all(not (e.target_type == "slice" and e.target_id == other.id) for e in events)


@pytest.mark.django_db
def test_spec_is_boxed_inline_edit(client_local, org):
    from pathlib import Path
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Design"), title="spec slice")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="section-label">Spec' in body          # labeled section
    # Substring, not the whole class attribute: spec is a long-form surface, so
    # it also carries .spec-edit--tall. What this line pins is that the inline
    # editor is there at all, not the exact attribute spelling.
    assert "spec-edit" in body                           # inline editor present
    assert 'rows="6"' not in body                        # no big fixed textarea jump
    # Spec reads as a field: boxed like the other props (border + background).
    css = (Path(__file__).resolve().parents[2] / "tuckit" / "web" / "static" / "web" / "app.css").read_text()
    assert ".spec, .spec-edit {" in css                  # shared box rule present


# --- no Ticket surface left in the panel ---------------------------------
#
# 0045 appended every capture body into the slice's own spec, so the "From:
# TCK-n" provenance row (and the "the original capture is in ..." empty state
# that pointed at it) had nothing left to reach: the text is IN the spec now,
# and the ?ticket= links it rendered would only 302 back to this same slice.


@pytest.mark.django_db
def test_panel_shows_no_ticket_provenance(client_local, org):
    from tuckit.core.services.tickets import create_ticket, promote_ticket

    area = create_area(org, "Backend")
    origin = create_ticket(org, "Origin", body="the capture", area=area)
    s = promote_ticket(origin, area=area)

    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "From:" not in body
    assert f"?ticket={origin.id}" not in body
    assert "No design doc yet" not in body      # the ticket-shaped empty state
    assert "Add a spec" in body                 # ...replaced by the generic one


@pytest.mark.django_db
def test_unlinked_slice_keeps_the_generic_prompt(client_local, org):
    s = create_slice(org, area=create_area(org, "Backend"), title="Direct")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "Add a spec" in body
    assert "No design doc yet" not in body


@pytest.mark.django_db
def test_slice_with_a_spec_shows_no_empty_state(client_local, org):
    from tuckit.core.services.slices import update_slice

    area = create_area(org, "Backend")
    s = create_slice(org, area=area, title="Origin")
    update_slice(s, spec="## Design\nreal content")

    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "No design doc yet" not in body
    assert "Click to add a spec" not in body


@pytest.mark.django_db
def test_slice_spec_table_reaches_the_page(client_local, org):
    """The renderer is unit-tested; this proves the rendered table actually
    survives the template + autoescaping path onto the page."""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Has a table", spec="| col | val |\n| --- | --- |\n| a | 1 |")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "<table>" in body
    assert "<th>col</th>" in body


# --- A0: status is never a control, only a Ship/Drop consequence -----------


@pytest.mark.django_db
def test_slice_edit_form_offers_no_status_control(client_local, org):
    """The create/edit slice form has no status select — Ship/Drop are the
    only way a status changes."""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="아무거나", spec="왜", status="open")

    html = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert 'name="status"' not in html


@pytest.mark.django_db
def test_slice_detail_offers_no_status_menu(client_local, org):
    """No status-picking menu — stage is read-only. (The Area picker also uses
    a dropdown, but its option buttons carry `area-opt`, not `status-opt`, so
    this stays a precise check on the status control specifically.)"""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="아무거나", spec="왜", status="open")

    html = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "status-opt" not in html
    assert 'class="status-pill status-pill--static"' in html


@pytest.mark.django_db
def test_stage_pill_shows_human_label_not_raw_key(client_local, org):
    """The pill must never leak the raw snake_case stage key as visible text
    — `board_label` turns needs_design/needs_steps/ready_to_ship into readable
    text, the same filter the Board already uses. (The raw key
    legitimately still appears inside the dot's `status-dot--needs_design`
    CSS class — ">needs_design<" pins the rendered TEXT, not the class.)"""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="no spec yet")   # stage: needs_design

    html = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert ">needs_design<" not in html
    assert "Needs design" in html


@pytest.mark.django_db
def test_ready_to_ship_slice_can_ship_from_detail(client_local, org):
    """Removing the status dropdown must not remove the ability to ship from
    the modal — it was the only path there."""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="다 됐다", spec="왜", status="open")
    b = create_bite(s, "한 걸음")
    from tuckit.core.services.bites import update_bite
    update_bite(b, status="done")

    html = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "Ship it" in html


@pytest.mark.django_db
def test_dropped_slice_restores_to_open(client_local, org):
    """Restore used to send status='planned', now invalid — it must send
    'open' or set_slice_status() 400s."""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="접은 일", spec="왜", status="dropped")

    resp = client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "open"})

    s.refresh_from_db()
    assert resp.status_code == 200
    assert s.status == "open"


@pytest.mark.django_db
def test_shipped_slice_can_reopen_from_detail(client_local, org):
    """The old status dropdown could restore a shipped slice back to backlog;
    that path is gone, so the action bar needs its own Reopen."""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="출시됨", spec="왜", status="shipped")

    body = client_local.get(f"/{org.slug}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert "Reopen" in body

    resp = client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "open"})
    s.refresh_from_db()
    assert resp.status_code == 200
    assert s.status == "open"


# --- Task 10: one modal that GROWS with the slice ---------------------------
#
# There is no second detail type any more. An Inbox slice (no area) shows only
# what you need to judge it — ref, title, who captured it, spec, Area picker.
# Picking an area makes the rest appear; clearing it collapses back. That is
# progressive disclosure, not a type conversion, which is exactly why the old
# one-way Promote could be deleted.


@pytest.mark.django_db
def test_inbox_slice_modal_hides_steps_and_stage(client_local, org):
    s = create_slice(org, title="정리 안 됨", spec="본문")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/?modal=1").content.decode()
    assert "본문" in body
    assert "Steps" not in body
    assert "Constraints" not in body
    assert "Stage" not in body


@pytest.mark.django_db
def test_filed_slice_modal_shows_the_full_surface(client_local, org, area):
    s = create_slice(org, area=area, title="정리됨", spec="본문")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/?modal=1").content.decode()
    assert "Steps" in body
    assert "Constraints" in body
    assert "Stage" in body


@pytest.mark.django_db
def test_constraints_are_editable_and_persist(client_local, org, area):
    s = create_slice(org, area=area, title="s", spec="본문")
    client_local.post(f"/{org.slug}/slices/{s.id}/edit", {"constraints": "hx-swap 명시"})
    s.refresh_from_db()
    assert s.constraints == "hx-swap 명시"


@pytest.mark.django_db
def test_no_plan_vocabulary_anywhere_in_the_modal(client_local, org, area):
    s = create_slice(org, area=area, title="s", spec="본문")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/?modal=1").content.decode()
    for word in ("Add plan", "Plan title", "Delete plan", "Overview"):
        assert word not in body


@pytest.mark.django_db
def test_constraints_empty_state_teaches_what_belongs_there(client_local, org, area):
    """The placeholder is the ONLY place in the product that explains what a
    constraint is. A bare "Add constraints…" would leave the field's whole
    purpose undocumented — and this field is the release's point."""
    s = create_slice(org, area=area, title="s", spec="본문")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "landmines" in body
    assert 'aria-label="Edit constraints"' in body


@pytest.mark.django_db
def test_constraints_render_as_markdown_and_are_sanitized(client_local, org, area):
    s = create_slice(org, area=area, title="s", spec="본문",
                     constraints="## 지뢰\n<script>alert(1)</script>")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    block = re.search(r'<div class="desc-block constraints-block">.*?</form>', body, re.S).group(0)
    assert "<h2" in block
    assert "<script>alert(1)</script>" not in block


@pytest.mark.django_db
def test_picking_an_area_grows_the_same_modal(client_local, org, area):
    """The Inbox modal's one control files the slice through the SAME endpoint
    Task 9 built (reversible), and the panel then carries the full surface.
    Driven through the real routes, not the service."""
    s = create_slice(org, title="정리 안 됨", spec="본문")
    picker = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert f"/slices/{s.id}/area" in picker

    client_local.post(f"/{org.slug}/slices/{s.id}/area", {"area_id": area.id})
    grown = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "Steps" in grown and "Constraints" in grown and "Stage" in grown

    # ...and clearing it collapses back. Nothing here is one-way.
    client_local.post(f"/{org.slug}/slices/{s.id}/area", {"area_id": ""})
    back = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "Steps" not in back


@pytest.mark.django_db
def test_inbox_slice_offers_no_ship_or_drop(client_local, org):
    """Ship/Drop are decisions about work you committed to. An unfiled capture
    is not that yet — the decision it needs is an area."""
    s = create_slice(org, title="정리 안 됨", spec="본문")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "Ship it" not in body
    assert "Drop slice" not in body
    assert "Copy link" in body      # still addressable


@pytest.mark.django_db
def test_steps_are_added_on_the_slice_not_a_plan(client_local, org, area):
    """The add-step form posts to the slice's own route. Bites hang off the
    Slice (Task 5) — the plan-scoped route and the reparenting shim behind it
    are gone."""
    from tuckit.core.models import Bite

    s = create_slice(org, area=area, title="s", spec="본문")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert f"/slices/{s.id}/steps" in body

    resp = client_local.post(f"/{org.slug}/slices/{s.id}/steps", {"title": "첫 걸음"},
                             HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    b = Bite.objects.get(slice=s)
    assert b.title == "첫 걸음"
    assert b.plan_id is None
    assert "첫 걸음" in resp.content.decode()


@pytest.mark.django_db
def test_agent_added_steps_are_visible_in_the_panel(client_local, org, area):
    """A bite created straight on the slice (what add_bites does now) must
    render. Before Task 10 the panel only listed bites nested under a plan, so
    an agent's step was created correctly and stayed invisible."""
    from tuckit.core.services.bites import add_bites

    s = create_slice(org, area=area, title="s", spec="본문")
    add_bites(s, [{"title": "에이전트가 넣은 단계"}], source="agent")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "에이전트가 넣은 단계" in body


@pytest.mark.django_db
def test_the_panel_area_picker_declares_its_own_hx_swap(client_local, org, area):
    """htmx INHERITS hx-swap from ancestors. This select sits inside the
    detail panel, whose editors carry hx-swap="outerHTML" on the surrounding
    forms — without an explicit swap the response would be spliced over the
    panel instead of doing its OOB work, and no endpoint test would see it
    (the endpoint is fine). Same guard the Inbox row's copy has."""
    s = create_slice(org, title="정리 안 됨")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    start = body.index('class="inbox-area-select"')
    tag = body[body.rindex("<select", 0, start):body.index(">", start)]
    assert 'hx-swap="none"' in tag
    assert f"/slices/{s.id}/area" in tag


# --- Fix round 1 -----------------------------------------------------------


@pytest.mark.django_db
def test_a_dropped_slice_says_so_even_with_no_area(client_local, org):
    """0045 turned every dismissed/duplicate ticket into a dropped slice while
    copying its area — NULL for anything dismissed before it was filed. Those
    rows are in no Inbox (inbox_slices() takes open only) and on no Area board,
    and the ?ticket= redirect is the one path that reaches them. Gated behind
    `slice.area` the panel greeted them as a fresh capture: no "dropped" tag,
    no Restore, and a picker inviting you to file something someone threw
    away."""
    s = create_slice(org, title="기각된 것", spec="본문", status="dropped")

    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "dropped" in body
    assert "Restore" in body

    resp = client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "open"})
    s.refresh_from_db()
    assert resp.status_code == 200
    assert s.status == "open"           # ...and Restore actually restores it


@pytest.mark.django_db
def test_an_area_less_shipped_slice_can_still_be_reopened(client_local, org):
    s = create_slice(org, title="출시됨", spec="본문", status="shipped")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "Reopen" in body


@pytest.mark.django_db
def test_filing_from_the_panel_returns_the_grown_panel(client_local, org, area):
    """The interaction this release is built on, asserted on the RESPONSE —
    what the browser is actually handed — not on a later GET. The panel grows
    in place (OOB over .detail-body) and the modal must NOT be closed out from
    under the reader."""
    s = create_slice(org, title="정리 안 됨", spec="본문")

    body = client_local.post(
        f"/{org.slug}/slices/{s.id}/area?modal=1",
        {"area_id": area.id, "from": "detail"}, HTTP_HX_REQUEST="true",
    ).content.decode()

    assert 'hx-swap-oob="outerHTML:.detail-body"' in body
    assert "detail-card" in body                     # re-rendered AS a modal card
    assert "Stage" in body and "Constraints" in body and "Steps" in body
    assert "Drop slice" in body
    # the modal-clearing OOB must be absent, or the panel would be swapped into
    # a container that was just emptied
    assert 'hx-swap-oob="innerHTML:#detail-modal"' not in body
    # ...and the feedback the Inbox path gives is still there
    assert f"Filed in {area.name}." in body
    assert "Undo" in body


@pytest.mark.django_db
def test_clearing_the_area_from_the_panel_collapses_it_in_place(client_local, org, area):
    s = create_slice(org, area=area, title="정리됨", spec="본문")

    body = client_local.post(
        f"/{org.slug}/slices/{s.id}/area?modal=1",
        {"area_id": "", "from": "detail"}, HTTP_HX_REQUEST="true",
    ).content.decode()

    assert 'hx-swap-oob="outerHTML:.detail-body"' in body
    assert "Steps" not in body and "Constraints" not in body and "Stage" not in body
    assert "inbox-area-select" in body               # collapsed back to the picker
    assert "Moved back to Inbox." in body
    # Undo must reverse the direction that actually happened AND re-render the
    # panel the same way, or the slice moves while the panel on screen lies.
    assert f'"area_id": "{area.id}"' in body
    assert '"from": "detail"' in body


@pytest.mark.django_db
def test_the_inbox_row_path_still_closes_the_modal_and_sends_no_panel(client_local, org, area):
    """The row fires the same endpoint from a page where the only `.detail-body`
    could be some OTHER slice's panel — so the panel is gated on `from=detail`,
    not sent to everyone."""
    s = create_slice(org, title="정리 안 됨")

    body = client_local.post(
        f"/{org.slug}/slices/{s.id}/area", {"area_id": area.id}, HTTP_HX_REQUEST="true",
    ).content.decode()

    assert 'hx-swap-oob="outerHTML:.detail-body"' not in body
    assert 'hx-swap-oob="innerHTML:#detail-modal"' in body
    assert f"Filed in {area.name}." in body
