import pytest


@pytest.mark.django_db
def test_home_lists_building_and_attention(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    backend = create_area(workspace, "Backend")
    create_slice(backend, "Payments work", status="building")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert "Payments work" in body
    assert "<span>focus</span>" in body   # building slices now live in the Focus column


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
def test_home_stale_building_slice_not_duplicated_in_now(client_local, workspace):
    from datetime import timedelta
    from django.utils import timezone
    from tuckit.core.models import Slice
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(workspace, "제품")
    s = create_slice(a, "정체된 빌딩 슬라이스", status="building")
    Slice.objects.filter(pk=s.pk).update(updated_at=timezone.now() - timedelta(days=9))
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert "9d idle" in body                       # confirms it landed in Needs you/Attention
    assert body.count("정체된 빌딩 슬라이스") == 1   # must not also repeat in the Now group


@pytest.mark.django_db
def test_home_all_clear_when_no_attention(client_local, workspace):
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert "Nothing needs your attention right now." in body       # confident done signal
    assert "all-clear" in body


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
    assert "<span>needs_you</span>" in body
    assert "<span>focus</span>" in body and "<span>doing</span>" in body and "<span>next</span>" in body
    assert 'class="button button-small"' in body   # page-head Capture button


@pytest.mark.django_db
def test_home_shows_doing_bites_and_planned_in_next(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    a = create_area(workspace, "Backend")
    s = create_slice(a, "Building slice", status="building")
    create_bite(s, "Active bite", status="doing")
    create_slice(a, "Planned next", status="planned")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert "Active bite" in body           # doing bite in the Doing column
    assert "Planned next" in body          # planned slice in the Next column
    assert "<span>next</span>" in body


@pytest.mark.django_db
def test_home_now_row_shows_spec_summary(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(workspace, "Backend")
    create_slice(a, "결제 도입", status="building",
                 spec="---\nname: billing\n---\n# 한 줄 요약 캡션\n본문 이어짐")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="row-desc"' in body      # one-line caption slot rendered
    assert "한 줄 요약 캡션" in body        # first meaningful spec line, markdown stripped


@pytest.mark.django_db
def test_home_active_headers_present(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    a = create_area(workspace, "Backend")
    s = create_slice(a, "Building slice", status="building")
    create_bite(s, "Doing bite", status="doing")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    # needs_you / Overview / recently_shipped are titled section boxes; the
    # Focus/Doing/Next columns live inside the Overview box.
    assert 'class="home-section"' in body
    assert 'class="home-cols"' in body
    assert "<span>doing</span>" in body


@pytest.mark.django_db
def test_home_sections_are_titled_boxes(client_local, workspace):
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    # Three titled boxes: needs_you, Overview (the columns), recently_shipped.
    assert body.count('class="home-section"') >= 3
    assert "<span>Overview</span>" in body
    assert "<span>needs_you</span>" in body
    assert "<span>recently_shipped</span>" in body


@pytest.mark.django_db
def test_home_building_row_shows_progress_bar(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    a = create_area(workspace, "Backend")
    s = create_slice(a, "결제 도입", status="building")
    create_bite(s, "완료된 것", status="done")
    create_bite(s, "남은 것", status="todo")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="row-prog-track"' in body   # thin bar on the building row
    assert "width:50%" in body                # 1 of 2 bites done
    assert "1/2" in body


@pytest.mark.django_db
def test_slice_row_has_status_dot_and_arrow(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    create_slice(create_area(workspace, "Backend"), "row look", status="building")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="status-dot' in body     # status indicator kept
    assert 'class="row-arrow"' in body     # quiet trailing affordance


@pytest.mark.django_db
def test_home_shows_summary_cards(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(workspace, "Backend")
    create_slice(a, "Building one", status="building")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="stat-cards"' in body
    assert "Building" in body and "Backlog" in body
    assert "Shipped this week" in body and "Needs attention" in body


@pytest.mark.django_db
def test_home_header_has_subtitle_not_count(client_local, workspace):
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert "Today's progress and what to focus on next" in body


@pytest.mark.django_db
def test_home_recently_shipped_strip_shows_items(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    a = create_area(workspace, "Design")
    create_slice(a, "Shipped feature", status="shipped")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="shipped-strip"' in body
    assert "Shipped feature" in body
    assert "<span>recently_shipped</span>" in body


@pytest.mark.django_db
def test_home_recently_shipped_caps_and_links(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    workspace.shipped_board_mode = "count"
    workspace.shipped_board_limit = 1
    workspace.save(update_fields=["shipped_board_mode", "shipped_board_limit"])
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Design")
    create_slice(a, "shipped one", status="shipped")
    create_slice(a, "shipped two", status="shipped")
    body = client_local.get(f"{p}/").content.decode()
    assert "View all (2)" in body                 # true total in the overflow link
    assert "status=shipped" in body               # unified view-all link
