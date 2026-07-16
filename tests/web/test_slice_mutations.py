import pytest
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite
from tuckit.core.models import Slice, Bite

@pytest.mark.django_db
def test_status_change_updates_and_returns_panel(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "B"), "x", status="planned")
    resp = client_local.post(f"{p}/slices/{s.id}/status", {"status": "building"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert Slice.objects.get(pk=s.id).status == "building"

@pytest.mark.django_db
def test_invalid_status_rejected(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "B"), "x", status="planned")
    resp = client_local.post(f"{p}/slices/{s.id}/status", {"status": "blocked"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 400
    assert Slice.objects.get(pk=s.id).status == "planned"

@pytest.mark.django_db
def test_bite_toggle(client_local, workspace):
    """Bites are no longer hand-added from the panel; they're authored via a
    Plan (by an agent or the plan API) and only toggled here."""
    from tuckit.core.services.plans import create_plan
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "B"), "x")
    plan_ = create_plan(s, title="Plan")
    b = create_bite(plan_, "웹훅")
    assert b.status == "todo"
    client_local.post(f"{p}/bites/{b.id}/toggle", HTTP_HX_REQUEST="true")
    assert Bite.objects.get(pk=b.id).status == "done"

@pytest.mark.django_db
def test_spec_edit(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "B"), "x")
    client_local.post(f"{p}/slices/{s.id}/edit", {"spec": "새 스펙"}, HTTP_HX_REQUEST="true")
    assert Slice.objects.get(pk=s.id).spec == "새 스펙"

@pytest.mark.django_db
def test_status_control_is_dropdown(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "제품"), "X", status="building")
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="status-menu"' in body           # status control re-rendered after change
    assert "status-opt--on" in body                # active option marked

@pytest.mark.django_db
def test_bite_body_updates_and_renders(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    from tuckit.core.services.plans import create_plan
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "제품"), "슬라이스")
    b = create_bite(create_plan(s, title="Plan"), "Slack 연동")
    resp = client_local.post(f"{p}/bites/{b.id}/body", {"body": "## 설계\n실패 시 재시도"})
    assert resp.status_code == 200
    b.refresh_from_db()
    assert "재시도" in b.body
    assert "<h2" in resp.content.decode()      # markdown rendered in the row

@pytest.mark.django_db
def test_bite_body_is_sanitized(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    from tuckit.core.services.plans import create_plan
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "제품"), "슬라이스")
    b = create_bite(create_plan(s, title="Plan"), "위험", body="<script>alert(1)</script>정상")
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert "<script>" not in body
    assert "정상" in body

@pytest.mark.django_db
def test_slice_tag_add_then_remove(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "제품"), "태그 편집")

    resp = client_local.post(f"{p}/slices/{s.id}/tags", {"add": "billing"})
    assert resp.status_code == 200
    assert "billing" in resp.content.decode()
    assert list(s.tags.values_list("name", flat=True)) == ["billing"]

    resp = client_local.post(f"{p}/slices/{s.id}/tags", {"remove": "billing"})
    assert resp.status_code == 200
    assert s.tags.count() == 0

@pytest.mark.django_db
def test_slice_panel_active_shows_drop_control(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "제품"), "진행 중인 것", status="building")
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert "Drop" in body

@pytest.mark.django_db
def test_slice_panel_dropped_shows_restore(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "제품"), "버린 것", status="dropped")
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert "Restore" in body
    # restoring puts it back into the flow
    resp = client_local.post(f"{p}/slices/{s.id}/status", {"status": "idea"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.status == "idea"

@pytest.mark.django_db
def test_slice_panel_shows_byline(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "제품"), "메타 확인")  # default source=human
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="props"' in body
    assert "Created" in body
    assert "Updated" in body

@pytest.mark.django_db
def test_bite_source_time_renders_korean(client_local, workspace):
    from datetime import timedelta
    from django.utils import timezone
    from tuckit.core.models import Bite
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    from tuckit.core.services.plans import create_plan
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "제품"), "슬라이스")
    b = create_bite(create_plan(s, title="Plan"), "노트 bite", body="## 메모")
    Bite.objects.filter(pk=b.pk).update(updated_at=timezone.now() - timedelta(hours=2, minutes=30))
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    # timesince now renders in Korean, not "2 hours, 30 minutes"
    assert "hours" not in body and "minutes" not in body
    assert "시간" in body
