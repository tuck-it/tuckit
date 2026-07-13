import pytest


@pytest.mark.django_db
def test_home_lists_building_and_attention(client_local, workspace):
    from tuckit.core.services.areas import create_area, get_or_create_triage
    from tuckit.core.services.slices import create_slice
    backend = create_area(workspace, "Backend")
    create_slice(backend, "결제 도입", status="building")
    resp = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/")
    body = resp.content.decode()
    assert "결제 도입" in body
    assert "Now" in body   # building group label


@pytest.mark.django_db
def test_home_sidebar_excludes_triage_area(client_local, workspace):
    from tuckit.core.services.areas import create_area
    create_area(workspace, "Backend")
    resp = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/")
    body = resp.content.decode()
    assert "/areas/backend/" in body
    assert "/areas/triage/" not in body


@pytest.mark.django_db
def test_tags_render_with_hash_span(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(workspace, "제품")
    create_slice(a, "태그 있는 슬라이스", status="building", tags=["billing"])
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
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
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert "9d idle" in body
    assert 'class="panel"' in body           # rows are in a unified panel


@pytest.mark.django_db
def test_home_all_clear_when_no_attention(client_local, workspace):
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert "Nothing needs your attention right now." in body       # confident done signal
    assert "all-clear" in body


@pytest.mark.django_db
def test_home_tail_contains_shipped_items(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(workspace, "제품")
    create_slice(a, "배포된 기능", status="shipped")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert "tail-body" in body
    assert "배포된 기능" in body   # tail content present in DOM (x-show only toggles visibility)


@pytest.mark.django_db
def test_home_omits_roadmap_strip_and_recent_activity(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice, set_slice_status
    a = create_area(workspace, "Backend")
    s = create_slice(a, "빌딩", status="planned")
    set_slice_status(s, "building")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="roadmap-strip"' not in body        # moved off Home
    assert "Recent activity" not in body              # moved off Home
    assert f'href="/{workspace.org.slug}/{workspace.slug}/roadmap/"' in body                 # Board still reachable via sidebar
    assert '/activity/?panel=1' in body               # Activity via the utility bell


@pytest.mark.django_db
def test_home_has_heading_and_capture(client_local, workspace):
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="page-head"' in body
    assert "Needs you" in body and "Now" in body and "Doing" in body
    assert "Next" not in body                       # planned pipeline moved to Board
    # a capture action is present in the page header (reuses the capture modal)
    assert 'class="button button-small"' in body   # page-head Capture button


@pytest.mark.django_db
def test_home_shows_doing_bites_and_no_planned(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    a = create_area(workspace, "Backend")
    s = create_slice(a, "빌딩 슬라이스", status="building")
    create_bite(s, "지금 하는 것", status="doing")
    create_slice(a, "다음 계획", status="planned")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert "지금 하는 것" in body                    # doing bite on Home
    assert "다음 계획" not in body                   # planned NOT on Home (it's on Board)


@pytest.mark.django_db
def test_slice_row_has_status_dot_and_arrow(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    create_slice(create_area(workspace, "Backend"), "row look", status="building")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="status-dot' in body     # status indicator kept
    assert 'class="row-arrow"' in body     # quiet trailing affordance
