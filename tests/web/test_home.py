import pytest


@pytest.mark.django_db
def test_home_lists_building_and_attention(client_local, workspace):
    from tuckit.core.services.areas import create_area, get_or_create_triage
    from tuckit.core.services.slices import create_slice
    backend = create_area(workspace, "Backend")
    create_slice(backend, "결제 도입", status="building")
    resp = client_local.get("/")
    body = resp.content.decode()
    assert "결제 도입" in body
    assert "Now" in body   # building group label


@pytest.mark.django_db
def test_home_sidebar_excludes_triage_area(client_local, workspace):
    from tuckit.core.services.areas import create_area
    create_area(workspace, "Backend")
    resp = client_local.get("/")
    body = resp.content.decode()
    assert "/areas/backend/" in body
    assert "/areas/triage/" not in body


@pytest.mark.django_db
def test_tags_render_with_hash_span(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(workspace, "제품")
    create_slice(a, "태그 있는 슬라이스", status="building", tags=["billing"])
    body = client_local.get("/").content.decode()
    assert 'class="tag-hash"' in body


@pytest.mark.django_db
def test_home_attention_shows_reason_label(client_local, workspace):
    from datetime import timedelta
    from django.utils import timezone
    from tuckit.core.models import Slice
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(workspace, "제품")
    s = create_slice(a, "정체된 작업", status="building")
    Slice.objects.filter(pk=s.pk).update(updated_at=timezone.now() - timedelta(days=9))
    body = client_local.get("/").content.decode()
    assert "9d idle" in body
    assert 'class="panel"' in body           # rows are in a unified panel


@pytest.mark.django_db
def test_home_all_clear_when_no_attention(client_local, workspace):
    body = client_local.get("/").content.decode()
    assert "Nothing needs your attention right now." in body       # confident done signal
    assert "all-clear" in body


@pytest.mark.django_db
def test_home_tail_contains_shipped_items(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(workspace, "제품")
    create_slice(a, "배포된 기능", status="shipped")
    body = client_local.get("/").content.decode()
    assert "tail-body" in body
    assert "배포된 기능" in body   # tail content present in DOM (x-show only toggles visibility)


@pytest.mark.django_db
def test_home_omits_roadmap_strip_and_recent_activity(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice, set_slice_status
    a = create_area(workspace, "Backend")
    s = create_slice(a, "빌딩", status="planned")
    set_slice_status(s, "building")
    body = client_local.get("/").content.decode()
    assert 'class="roadmap-strip"' not in body        # moved off Home
    assert "Recent activity" not in body              # moved off Home
    assert 'href="/roadmap/"' in body                 # still reachable via sidebar
    assert 'href="/activity/"' in body


@pytest.mark.django_db
def test_home_has_heading_and_capture(client_local, workspace):
    body = client_local.get("/").content.decode()
    assert 'class="page-head"' in body
    assert "Needs you" in body and "Now" in body and "Next" in body
    # a capture action is present in the page header (reuses the capture modal)
    assert body.count("cap = true") >= 2   # sidebar Capture + page-head Capture
