import pytest
from datetime import timedelta
from django.utils import timezone
from tuckit.core.models import Slice, Workspace
from tuckit.core.services.areas import create_area, get_or_create_triage
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite
from tuckit.core.services.plans import create_plan


@pytest.mark.django_db
def test_attention_page_lists_stale_items(client_local, org):
    ws = Workspace.objects.get(org=org)
    a = create_area(ws.org, "Backend")
    s = create_slice(a, "정체된 작업", status="building")
    Slice.objects.filter(pk=s.pk).update(updated_at=timezone.now() - timedelta(days=9))
    p = f"/{org.slug}/{ws.slug}"
    body = client_local.get(f"{p}/attention/").content.decode()
    assert "정체된 작업" in body
    assert "9d idle" in body


@pytest.mark.django_db
def test_attention_page_all_clear_when_empty(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    body = client_local.get(f"{p}/attention/").content.decode()
    assert "all-clear" in body
    assert 'class="panel"' in body   # empty state is carded, not floating bare text


@pytest.mark.django_db
def test_in_progress_page_shows_building_and_doing(client_local, org):
    ws = Workspace.objects.get(org=org)
    a = create_area(ws.org, "Backend")
    s = create_slice(a, "빌딩 슬라이스", status="building")
    create_bite(create_plan(s, title="Plan"), "두잉 바이트", status="doing")
    p = f"/{org.slug}/{ws.slug}"
    body = client_local.get(f"{p}/in-progress/").content.decode()
    assert "빌딩 슬라이스" in body
    assert "두잉 바이트" in body


@pytest.mark.django_db
def test_roadmap_page_shows_distribution_and_slices(client_local, org):
    ws = Workspace.objects.get(org=org)
    a = create_area(ws.org, "Backend")
    create_slice(a, "로드맵 항목", status="planned")
    create_slice(get_or_create_triage(ws.org), "캡처", status="idea")  # excluded
    p = f"/{org.slug}/{ws.slug}"
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "로드맵 항목" in body
    assert 'data-status="planned"' in body   # rendered in its status column
    assert "캡처" not in body   # triage slices excluded from roadmap


@pytest.mark.django_db
def test_board_page_heading(client_local, org):
    ws = Workspace.objects.get(org=org)
    p = f"/{org.slug}/{ws.slug}"
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert '<h1 class="page-title">Board</h1>' in body
