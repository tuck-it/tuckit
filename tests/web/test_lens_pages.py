import pytest
from datetime import timedelta
from django.utils import timezone
from tuckit.core.models import Slice
from tuckit.core.services.areas import create_area, get_or_create_triage
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite


@pytest.mark.django_db
def test_attention_page_lists_stale_items(client_local, workspace):
    a = create_area(workspace, "Backend")
    s = create_slice(a, "정체된 작업", status="building")
    Slice.objects.filter(pk=s.pk).update(updated_at=timezone.now() - timedelta(days=9))
    body = client_local.get("/attention/").content.decode()
    assert "정체된 작업" in body
    assert "9일째 진척 없음" in body


@pytest.mark.django_db
def test_attention_page_all_clear_when_empty(client_local, workspace):
    body = client_local.get("/attention/").content.decode()
    assert "all-clear" in body


@pytest.mark.django_db
def test_in_progress_page_shows_building_and_doing(client_local, workspace):
    a = create_area(workspace, "Backend")
    s = create_slice(a, "빌딩 슬라이스", status="building")
    create_bite(s, "두잉 바이트", status="doing")
    body = client_local.get("/in-progress/").content.decode()
    assert "빌딩 슬라이스" in body
    assert "두잉 바이트" in body


@pytest.mark.django_db
def test_roadmap_page_shows_distribution_and_slices(client_local, workspace):
    a = create_area(workspace, "Backend")
    create_slice(a, "로드맵 항목", status="planned")
    create_slice(get_or_create_triage(workspace), "캡처", status="idea")  # excluded
    body = client_local.get("/roadmap/").content.decode()
    assert "로드맵 항목" in body
    assert "Planned" in body
    assert "캡처" not in body   # triage slices excluded from roadmap
