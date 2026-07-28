import pytest
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite
from tuckit.core.models import Slice, Bite

@pytest.mark.django_db
def test_status_change_updates_and_returns_panel(client_local, org):
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x", status="open")
    resp = client_local.post(f"{p}/slices/{s.id}/status", {"status": "shipped"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert Slice.objects.get(pk=s.id).status == "shipped"

@pytest.mark.django_db
def test_invalid_status_rejected(client_local, org):
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x", status="open")
    resp = client_local.post(f"{p}/slices/{s.id}/status", {"status": "blocked"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    assert Slice.objects.get(pk=s.id).status == "open"

@pytest.mark.django_db
def test_step_create_adds_to_the_slice(client_local, org):
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    resp = client_local.post(
        f"{p}/slices/{s.id}/steps", {"title": "Retry webhook"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 200
    assert [b.title for b in Bite.objects.filter(slice=s)] == ["Retry webhook"]
    assert "Retry webhook" in resp.content.decode()


@pytest.mark.django_db
def test_step_create_rejects_empty_title(client_local, org):
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    resp = client_local.post(f"{p}/slices/{s.id}/steps", {"title": "  "}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    assert Bite.objects.filter(slice=s).count() == 0


@pytest.mark.django_db
def test_step_create_on_a_foreign_slice_404s(client_local, org):
    from tuckit.core.models import Org
    other = Org.objects.create(name="Other", slug="other")
    foreign = create_slice(other, area=create_area(other, "F"), title="s")
    resp = client_local.post(
        f"/{org.slug}/slices/{foreign.id}/steps", {"title": "x"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_bite_edit_renames(client_local, org):
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    b = create_bite(s, "old")
    resp = client_local.post(f"{p}/bites/{b.id}/edit", {"title": "new"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    b.refresh_from_db()
    assert b.title == "new"
    assert "new" in resp.content.decode()


@pytest.mark.django_db
def test_bite_delete_removes_it(client_local, org):
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    b = create_bite(s, "gone")
    resp = client_local.post(f"{p}/bites/{b.id}/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert Bite.objects.filter(pk=b.id).count() == 0


@pytest.mark.django_db
def test_bite_row_has_rename_and_delete_controls(client_local, org):
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    b = create_bite(s, "step")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert f"/bites/{b.id}/edit" in body
    assert f"/bites/{b.id}/delete" in body


@pytest.mark.django_db
def test_panel_shows_the_steps_empty_state_and_the_add_form(client_local, org):
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")  # no steps
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert "No steps yet" in body                    # teaching empty state
    assert "let your agent fill them in" in body     # copy signals both authors
    assert f"/slices/{s.id}/steps" in body           # add-step form always present


@pytest.mark.django_db
def test_focus_bite_autofocuses_add_bite_on_full_page(client_local, org):
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    body = client_local.get(f"{p}/slices/{s.id}/?focus=bite").content.decode()
    assert "$el.focus()" in body  # Alpine x-init focus hook rendered for focus=bite


@pytest.mark.django_db
def test_bite_toggle(client_local, org):
    """Steps can be authored from the panel (by a human) or through add_bites
    (by an agent); this endpoint only toggles done/todo."""
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    b = create_bite(s, "Webhook")
    assert b.status == "todo"
    client_local.post(f"{p}/bites/{b.id}/toggle", HTTP_HX_REQUEST="true")
    assert Bite.objects.get(pk=b.id).status == "done"

@pytest.mark.django_db
def test_spec_edit(client_local, org):
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    client_local.post(f"{p}/slices/{s.id}/edit", {"spec": "New spec"}, HTTP_HX_REQUEST="true")
    assert Slice.objects.get(pk=s.id).spec == "New spec"

@pytest.mark.django_db
def test_stage_pill_is_read_only(client_local, org):
    """The status dropdown is gone — stage renders as a static pill, and it
    re-renders correctly after a status change."""
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Product"), title="X", status="open")
    resp = client_local.post(f"{p}/slices/{s.id}/status", {"status": "shipped"}, HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    assert "status-opt" not in body
    assert 'class="status-pill status-pill--static"' in body
    assert "status-dot--shipped" in body            # pill reflects the new stage

@pytest.mark.django_db
def test_bite_body_updates_and_renders(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Product"), title="Slice")
    b = create_bite(s, "Slack integration")
    resp = client_local.post(f"{p}/bites/{b.id}/body", {"body": "## Design\nRetry on failure"})
    assert resp.status_code == 200
    b.refresh_from_db()
    assert "Retry on failure" in b.body
    assert "<h2" in resp.content.decode()      # markdown rendered in the row

@pytest.mark.django_db
def test_bite_body_is_sanitized(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Product"), title="Slice")
    from tuckit.core.services.bites import create_bite
    b = create_bite(s, "Risk", body="<script>alert(1)</script>ok")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert "<script>" not in body
    assert "ok" in body

@pytest.mark.django_db
def test_slice_tag_add_then_remove(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Product"), title="Edit tags")

    resp = client_local.post(f"{p}/slices/{s.id}/tags", {"add": "billing"})
    assert resp.status_code == 200
    assert "billing" in resp.content.decode()
    assert list(s.tags.values_list("name", flat=True)) == ["billing"]

    resp = client_local.post(f"{p}/slices/{s.id}/tags", {"remove": "billing"})
    assert resp.status_code == 200
    assert s.tags.count() == 0

@pytest.mark.django_db
def test_slice_detail_active_shows_drop_control(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Product"), title="In-progress item", status="open")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert "Drop" in body

@pytest.mark.django_db
def test_slice_detail_dropped_shows_restore(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Product"), title="Dropped item", status="dropped")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert "Restore" in body
    # restoring puts it back into the flow
    resp = client_local.post(f"{p}/slices/{s.id}/status", {"status": "open"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.status == "open"

@pytest.mark.django_db
def test_slice_detail_shows_byline(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Product"), title="Meta check")  # default source=human
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="props"' in body
    assert "Created" in body
    assert "Updated" in body

@pytest.mark.django_db
def test_bite_source_time_renders_english(client_local, org):
    from datetime import timedelta
    from django.utils import timezone
    from tuckit.core.models import Bite
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Product"), title="Slice")
    from tuckit.core.services.bites import create_bite
    b = create_bite(s, "Note bite", body="## Note")
    Bite.objects.filter(pk=b.pk).update(updated_at=timezone.now() - timedelta(hours=2, minutes=30))
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    # timesince now renders in English, not Korean
    assert "hours" in body and "minutes" in body


# --- One endpoint for "which area is this slice in" -------------------------
#
# The filed panel's area menu used to post to web:slice_reassign, a second
# endpoint that could only SET an area (int(request.POST["area_id"]), so an
# empty value 404'd) and answered with a bare panel — no toast, no Undo. That
# left the toast's 8-second Undo as the only way a human could send a filed
# slice back to the Inbox, while an agent could un-file forever. Both
# directions now go through web:slice_area, which is where the reversibility
# guarantee lives.


@pytest.mark.django_db
def test_the_reassign_endpoint_is_gone(client_local, org):
    """The route itself, not just its caller — a hand-made POST must not find a
    second, non-reversible way to set a slice's area."""
    from django.urls import NoReverseMatch, reverse
    a = create_area(org, "A")
    s = create_slice(a.org, area=a, title="s", source="human")
    with pytest.raises(NoReverseMatch):
        reverse("web:slice_reassign", args=[org.slug, s.id])
    assert client_local.post(
        f"/{org.slug}/slices/{s.id}/reassign", {"area_id": a.id}, HTTP_HX_REQUEST="true"
    ).status_code == 404


@pytest.mark.django_db
def test_panel_area_menu_posts_to_slice_area_and_offers_move_to_inbox(client_local, org):
    """The standing UI — not a toast that disappears — must be able to un-file."""
    a = create_area(org, "A")
    b = create_area(org, "B")
    s = create_slice(a.org, area=a, title="s", source="human")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()

    assert f"/slices/{s.id}/reassign" not in body
    # every menu item fires the reversible endpoint, with from=detail so the
    # panel re-renders in place
    assert body.count(f'hx-post="/{org.slug}/slices/{s.id}/area?modal=1"') == 3   # A, B, Move to Inbox
    assert f'hx-vals=\'{{"area_id": "{b.id}", "from": "detail"}}\'' in body
    assert 'hx-vals=\'{"area_id": "", "from": "detail"}\'' in body
    assert "Move to Inbox" in body


@pytest.mark.django_db
def test_area_menu_move_to_inbox_clears_the_area(client_local, org):
    a = create_area(org, "A")
    s = create_slice(a.org, area=a, title="move me", source="human")
    resp = client_local.post(
        f"/{org.slug}/slices/{s.id}/area", {"area_id": "", "from": "detail"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.area_id is None


@pytest.mark.django_db
def test_area_menu_can_still_move_between_areas(client_local, org):
    a = create_area(org, "A")
    b = create_area(org, "B")
    s = create_slice(a.org, area=a, title="move me", source="human")
    resp = client_local.post(
        f"/{org.slug}/slices/{s.id}/area", {"area_id": b.id, "from": "detail"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.area_id == b.id


@pytest.mark.django_db
def test_area_menu_foreign_area_404s(client_local, org):
    from tuckit.core.models import Org
    a = create_area(org, "A")
    s = create_slice(a.org, area=a, title="s", source="human")
    other = Org.objects.create(name="Other", slug="other")
    foreign = create_area(other, "Foreign")
    resp = client_local.post(
        f"/{org.slug}/slices/{s.id}/area", {"area_id": foreign.id, "from": "detail"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 404
    s.refresh_from_db()
    assert s.area_id == a.id


# --- Task 12: Ship/Drop/Restore/Reopen announce themselves ------------------
#
# Inbox actions (capture, filing/clearing an Area) already got a toast + Undo
# in Task 9/10, via capture._inbox_result() (now _feedback._action_result()).
# Ship/Drop/Restore/Reopen re-rendered the panel and said nothing — same
# mechanism, no reason the higher-stakes actions should be the quiet ones.


@pytest.mark.django_db
def test_dropping_a_slice_announces_it(client_local, org, area):
    s = create_slice(org, area=area, title="버릴 것", spec="설계")
    r = client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "dropped"})
    body = r.content.decode()
    assert "Dropped." in body
    assert 'id="toast"' in body


@pytest.mark.django_db
def test_dropping_a_slice_offers_undo(client_local, org, area):
    s = create_slice(org, area=area, title="버릴 것")
    r = client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "dropped"})
    body = r.content.decode()
    assert "Undo" in body
    assert f"/slices/{s.id}/status?undo_status=open" in body


@pytest.mark.django_db
def test_undo_after_dropping_restores_the_slice(client_local, org, area):
    """The toast's Undo button is a bare POST (no body) to a URL that already
    carries the old status in its own query string — mirroring the Inbox
    Undo's old-area-in-the-body trick, but the value has to live in the URL
    here because board.slice_move's queued-message Undo button has no hx-vals
    to attach a body to, and both entry points share this endpoint."""
    s = create_slice(org, area=area, title="버릴 것")
    client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "dropped"})
    s.refresh_from_db()
    assert s.status == "dropped"

    r = client_local.post(f"/{org.slug}/slices/{s.id}/status?undo_status=open")
    s.refresh_from_db()
    assert r.status_code == 200
    assert s.status == "open"


@pytest.mark.django_db
def test_undo_response_self_targets_the_panel_via_oob(client_local, org, area):
    """Fix round 1, C1: the toast's Undo button is hard-coded hx-swap="none"
    (_capture_result.html) — its own request has no target/swap that would
    ever place a *main* (non-oob) response body. Unless the re-rendered panel
    carries hx-swap-oob="outerHTML:.detail-body" itself, htmx silently drops
    it: the panel keeps showing the pre-Undo state (e.g. "Dropped" + Restore)
    while the toast claims the reversal happened and the database agrees with
    the toast, not the screen. Mirrors Task 10's analogous
    test_clearing_the_area_from_the_panel_collapses_it_in_place for the Area
    path. This must fail against the pre-fix code, which never set
    ctx["oob"] on this branch."""
    s = create_slice(org, area=area, title="패널도 맞아야 한다")
    client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "dropped"})

    undo_body = client_local.post(f"/{org.slug}/slices/{s.id}/status?undo_status=open").content.decode()

    assert 'hx-swap-oob="outerHTML:.detail-body"' in undo_body
    assert "Restored." in undo_body


@pytest.mark.django_db
def test_forward_status_response_does_not_self_target(client_local, org, area):
    """The panel's own Ship/Drop/Restore/Reopen buttons target
    `.detail-body` with hx-swap="outerHTML" directly — if THIS response also
    carried hx-swap-oob, htmx would have nothing non-oob to satisfy that
    primary swap, and the panel would go blank instead of growing/collapsing
    in place."""
    s = create_slice(org, area=area, title="정방향은 셀프타깃 아님")
    body = client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "dropped"}).content.decode()
    assert 'hx-swap-oob="outerHTML:.detail-body"' not in body


@pytest.mark.django_db
def test_shipping_a_slice_announces_it_with_undo(client_local, org, area):
    s = create_slice(org, area=area, title="끝난 것")
    r = client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "shipped"})
    body = r.content.decode()
    assert "Shipped." in body
    assert "Undo" in body
    assert f"/slices/{s.id}/status?undo_status=open" in body


@pytest.mark.django_db
def test_restoring_a_dropped_slice_announces_it(client_local, org, area):
    s = create_slice(org, area=area, title="되살릴 것", status="dropped")
    r = client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "open"})
    body = r.content.decode()
    assert "Restored." in body
    assert f"/slices/{s.id}/status?undo_status=dropped" in body  # Undo re-drops it


@pytest.mark.django_db
def test_reopening_a_shipped_slice_announces_it(client_local, org, area):
    s = create_slice(org, area=area, title="다시 열 것", status="shipped")
    r = client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "open"})
    body = r.content.decode()
    assert "Reopened." in body
    assert f"/slices/{s.id}/status?undo_status=shipped" in body  # Undo re-ships it


@pytest.mark.django_db
def test_status_toast_still_carries_the_re_rendered_panel(client_local, org, area):
    """The toast rides alongside the panel, not instead of it — filing from the
    panel (Task 10) has to keep growing/collapsing in place AND announce
    itself now."""
    s = create_slice(org, area=area, title="패널도 같이")
    r = client_local.post(f"/{org.slug}/slices/{s.id}/status", {"status": "shipped"})
    body = r.content.decode()
    assert 'class="detail-body' in body
    assert "status-dot--shipped" in body


@pytest.mark.django_db
def test_status_toast_keeps_the_modal_open(client_local, org, area):
    """Unlike Inbox filing (which closes the modal by default), a status
    change must NOT close it — the whole point is showing the new action bar
    in place."""
    s = create_slice(org, area=area, title="모달 유지")
    r = client_local.post(f"/{org.slug}/slices/{s.id}/status?modal=1", {"status": "shipped"})
    body = r.content.decode()
    assert 'hx-swap-oob="innerHTML:#detail-modal"' not in body


@pytest.mark.django_db
def test_moving_back_to_inbox_offers_undo(client_local, org, area):
    s = create_slice(org, area=area, title="되돌릴 것")
    r = client_local.post(f"/{org.slug}/slices/{s.id}/area", {"area_id": ""})
    body = r.content.decode()
    assert "Moved back to Inbox" in body
    assert "Undo" in body


