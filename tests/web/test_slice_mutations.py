import pytest
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite
from tuckit.core.models import Slice, Bite
from tests.web.conftest import bite_under_plan

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
def test_bite_create_adds_to_plan(client_local, org):
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    plan_ = create_plan(s, title="Plan")
    resp = client_local.post(
        f"{p}/plans/{plan_.id}/bites", {"title": "Retry webhook"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 200
    assert [b.title for b in Bite.objects.filter(plan=plan_)] == ["Retry webhook"]
    assert "Retry webhook" in resp.content.decode()


@pytest.mark.django_db
def test_bite_create_rejects_empty_title(client_local, org):
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    plan_ = create_plan(s, title="Plan")
    resp = client_local.post(f"{p}/plans/{plan_.id}/bites", {"title": "  "}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    assert Bite.objects.filter(plan=plan_).count() == 0


@pytest.mark.django_db
def test_bite_create_foreign_plan_404s(client_local, org):
    from tuckit.core.models import Org
    from tuckit.core.services.plans import create_plan
    other = Org.objects.create(name="Other", slug="other")
    foreign_plan = create_plan(create_slice(other, area=create_area(other, "F"), title="s"), title="P")
    resp = client_local.post(
        f"/{org.slug}/plans/{foreign_plan.id}/bites", {"title": "x"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_bite_edit_renames(client_local, org):
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    plan_ = create_plan(s, title="Plan")
    b = bite_under_plan(plan_, s, "old")
    resp = client_local.post(f"{p}/bites/{b.id}/edit", {"title": "new"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    b.refresh_from_db()
    assert b.title == "new"
    assert "new" in resp.content.decode()


@pytest.mark.django_db
def test_bite_delete_removes_it(client_local, org):
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    create_plan(s, title="Plan")
    b = create_bite(s, "gone")
    resp = client_local.post(f"{p}/bites/{b.id}/delete", HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert Bite.objects.filter(pk=b.id).count() == 0


@pytest.mark.django_db
def test_bite_row_has_rename_and_delete_controls(client_local, org):
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    plan_ = create_plan(s, title="Plan")
    b = bite_under_plan(plan_, s, "step")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert f"/bites/{b.id}/edit" in body
    assert f"/bites/{b.id}/delete" in body


@pytest.mark.django_db
def test_panel_shows_plan_empty_state_when_no_plan(client_local, org):
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")  # no plan
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert "No plan yet" in body            # teaching empty state
    assert f"/slices/{s.id}/plans" in body  # add-plan form always present


@pytest.mark.django_db
def test_panel_shows_add_bite_form_inside_plan(client_local, org):
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    plan_ = create_plan(s, title="Plan")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert f"/plans/{plan_.id}/bites" in body       # add-bite form target
    assert "let your agent fill these in" in body   # empty-bites copy signals both authors


@pytest.mark.django_db
def test_focus_bite_autofocuses_add_bite_on_full_page(client_local, org):
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    create_plan(s, title="Plan")
    body = client_local.get(f"{p}/slices/{s.id}/?focus=bite").content.decode()
    assert "$el.focus()" in body  # Alpine x-init focus hook rendered for focus=bite


@pytest.mark.django_db
def test_bite_toggle(client_local, org):
    """Bites can be authored from the panel (by a human) or via a Plan (by an
    agent or the plan API); this endpoint only toggles done/todo."""
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "B"), title="x")
    create_plan(s, title="Plan")
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
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Product"), title="Slice")
    create_plan(s, title="Plan")
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
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Product"), title="Slice")
    plan_ = create_plan(s, title="Plan")
    b = bite_under_plan(plan_, s, "Risk", body="<script>alert(1)</script>ok")
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
    from tuckit.core.services.plans import create_plan
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Product"), title="Slice")
    plan_ = create_plan(s, title="Plan")
    b = bite_under_plan(plan_, s, "Note bite", body="## Note")
    Bite.objects.filter(pk=b.pk).update(updated_at=timezone.now() - timedelta(hours=2, minutes=30))
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    # timesince now renders in English, not Korean
    assert "hours" in body and "minutes" in body


@pytest.mark.django_db
def test_slice_reassign_moves_area(client_local, org):
    a = create_area(org, "A")
    b = create_area(org, "B")
    s = create_slice(a.org, area=a, title="move me", source="human")
    resp = client_local.post(
        f"/{org.slug}/slices/{s.id}/reassign", {"area_id": b.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.area_id == b.id


@pytest.mark.django_db
def test_slice_reassign_foreign_area_404s(client_local, org):
    from tuckit.core.models import Org
    a = create_area(org, "A")
    s = create_slice(a.org, area=a, title="s", source="human")
    other = Org.objects.create(name="Other", slug="other")
    foreign = create_area(other, "Foreign")
    resp = client_local.post(
        f"/{org.slug}/slices/{s.id}/reassign", {"area_id": foreign.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_panel_shows_area_reassign_control(client_local, org):
    a = create_area(org, "A")
    create_area(org, "B")
    s = create_slice(a.org, area=a, title="s", source="human")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert f"/slices/{s.id}/reassign" in body
