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
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/attention/").content.decode()
    assert "정체된 작업" in body
    assert "9d idle" in body


@pytest.mark.django_db
def test_attention_page_all_clear_when_empty(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/attention/").content.decode()
    assert "all-clear" in body


@pytest.mark.django_db
def test_in_progress_page_shows_building_and_doing(client_local, workspace):
    a = create_area(workspace, "Backend")
    s = create_slice(a, "빌딩 슬라이스", status="building")
    create_bite(s, "두잉 바이트", status="doing")
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/in-progress/").content.decode()
    assert "빌딩 슬라이스" in body
    assert "두잉 바이트" in body


@pytest.mark.django_db
def test_roadmap_page_shows_distribution_and_slices(client_local, workspace):
    a = create_area(workspace, "Backend")
    create_slice(a, "로드맵 항목", status="planned")
    create_slice(get_or_create_triage(workspace), "캡처", status="idea")  # excluded
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "로드맵 항목" in body
    assert "Planned" in body
    assert "캡처" not in body   # triage slices excluded from roadmap


@pytest.mark.django_db
def test_activity_page_lists_events(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice, set_slice_status
    a = create_area(workspace, "Backend")
    s = create_slice(a, "로그인 리다이렉트", status="building")
    set_slice_status(s, "shipped")
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/activity/").content.decode()
    assert "로그인 리다이렉트" in body
    assert '/activity/?panel=1' in body   # Activity reachable via the utility bell


@pytest.mark.django_db
def test_sidebar_activity_is_bell_not_nav(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'aria-label="Activity"' in body and '/activity/?panel=1' in body
    nav_group = body.split('class="nav-group"')[1].split("</nav>")[0]
    assert ">Activity<" not in nav_group


@pytest.mark.django_db
def test_activity_panel_branch_returns_slideover(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice, set_slice_status
    a = create_area(workspace, "Backend")
    s = create_slice(a, "패널 이벤트", status="building")
    set_slice_status(s, "shipped")
    # panel branch: HX request with ?panel=1 returns just the slide-over inner
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/activity/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="panel-inner"' in body
    assert 'aria-label="Close panel"' in body
    assert "패널 이벤트" in body
    assert "<aside class=\"sidebar\"" not in body   # not the full page shell


@pytest.mark.django_db
def test_activity_full_page_still_works(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/activity/").content.decode()
    assert 'class="page-title"' in body            # full page, not panel


@pytest.mark.django_db
def test_board_page_heading(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert '<h1 class="page-title">Board</h1>' in body
