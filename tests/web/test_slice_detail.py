import re

import pytest
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite


@pytest.mark.django_db
def test_slice_full_page_renders_spec_and_bites(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Backend")
    s = create_slice(a, "결제 도입", spec="## 목표\nStripe 붙이기", status="building")
    create_bite(s, "SDK 연동", status="done")
    resp = client_local.get(f"{p}/slices/{s.id}/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "결제 도입" in body
    assert "<h2" in body            # markdown rendered
    assert "SDK 연동" in body


@pytest.mark.django_db
def test_slice_panel_is_partial(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Backend")
    s = create_slice(a, "X")
    resp = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    assert "<!doctype html>" not in body.lower()   # partial, not full page
    assert "X" in body


@pytest.mark.django_db
def test_spec_html_is_sanitized(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Backend")
    s = create_slice(
        a,
        "위험한 스펙",
        spec="## 제목\n<script>alert(1)</script>\n<img src=x onerror=alert(1)>",
    )
    resp = client_local.get(f"{p}/slices/{s.id}/")
    body = resp.content.decode()
    assert resp.status_code == 200
    # Scope assertions to the rendered spec_html output (the `spec` div).
    # base.html legitimately ships vendor <script> tags, and the edit form
    # intentionally shows the raw (auto-escaped) spec text in a <textarea>
    # for editing, so checking the whole page would collide with both.
    spec_section = re.search(r'<div class="spec".*?</div>', body, re.S).group(0)
    assert "<script>" not in spec_section
    assert "onerror" not in spec_section
    assert "<h2" in spec_section


@pytest.mark.django_db
def test_slice_other_workspace_404(client_local, workspace):
    from tuckit.core.models import Org, Workspace
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other = Workspace.objects.create(org=other_org, name="O", slug="o")
    s = create_slice(create_area(other, "A"), "secret")
    assert client_local.get(f"{p}/slices/{s.id}/").status_code == 404


@pytest.mark.django_db
def test_slice_panel_shows_its_activity_thread(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice, set_slice_status
    from tuckit.core.services.bites import create_bite
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Backend")
    s = create_slice(a, "스레드 슬라이스", status="idea")   # logs created (slice)
    set_slice_status(s, "building")                          # logs status_changed (slice)
    create_bite(s, "첫 바이트")                              # logs created (bite)
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="slice-activity"' in body                  # thread section present
    assert body.count('class="activity-row"') >= 3           # slice + status + bite events
    assert "첫 바이트" in body                               # bite event joined into the slice thread


@pytest.mark.django_db
def test_slice_panel_context_flags_and_progress(workspace):
    from tuckit.web.panel import slice_panel_context
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    s = create_slice(create_area(workspace, "Design"), "T")
    create_bite(s, "a", status="done")
    create_bite(s, "b")  # 1 of 2 done -> 50%

    panel = slice_panel_context(s, is_panel=True)
    assert panel["is_panel"] is True
    assert panel["panel_qs"] == "?panel=1"
    assert (panel["bites_done"], panel["bites_total"], panel["bites_pct"]) == (1, 2, 50)

    page = slice_panel_context(s)  # default is_panel=False
    assert page["is_panel"] is False
    assert page["panel_qs"] == ""


@pytest.mark.django_db
def test_panel_header_title_and_status_tabs(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Design")
    s = create_slice(a, "다크모드 폴리시", status="building")

    # panel context
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="panel-crumb"' in body
    assert f'href="/{workspace.org.slug}/{workspace.slug}/areas/{a.slug}/"' in body   # breadcrumb links to area
    assert "Design" in body
    assert 'class="panel-byline"' in body
    assert "seg--tabs" in body
    assert body.count('class="status-dot status-dot--') == 4    # a dot on every status tab
    assert "seg-item--on" in body                               # active (building) tab
    assert 'class="spec-box"' in body
    # panel-only chrome present
    assert "crumb-close" in body
    assert "Open full page" in body


@pytest.mark.django_db
def test_full_page_hides_panel_only_chrome(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Design")
    s = create_slice(a, "전체페이지")
    body = client_local.get(f"{p}/slices/{s.id}/").content.decode()   # full page, no panel=1
    assert "crumb-close" not in body        # no close button on the full page
    assert "Open full page" not in body     # no self-link on the full page
    assert 'class="panel-crumb"' in body    # breadcrumb still shown


@pytest.mark.django_db
def test_bites_progress_and_empty_state(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Design")
    s = create_slice(a, "S")

    # empty: card shown, no count
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="bites-empty"' in body
    assert "아직 bite가 없습니다" in body
    assert 'class="row-prog-track"' not in body   # no progress bar when there are no bites

    # with bites: count + progress shown, card gone
    create_bite(s, "a", status="done")
    create_bite(s, "b")
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="bites-empty"' not in body
    assert "1/2" in body
    assert 'class="row-prog-track"' in body
    assert "width: 50%" in body


@pytest.mark.django_db
def test_action_bar_has_copy_and_drop(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "Design"), "액션", status="building")
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="action-bar"' in body
    assert "Copy link" in body
    assert "Drop slice" in body


@pytest.mark.django_db
def test_context_tags_have_no_area_chip(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{workspace.org.slug}/{workspace.slug}"
    a = create_area(workspace, "Design")
    s = create_slice(a, "태그")
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="section-label">Context' in body
    assert "meta-area" not in body        # area chip removed from the tags row
    assert "Add tag" in body


@pytest.mark.django_db
def test_activity_timeline_has_nodes(client_local, workspace):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice, set_slice_status
    p = f"/{workspace.org.slug}/{workspace.slug}"
    s = create_slice(create_area(workspace, "Design"), "타임라인", status="idea")
    set_slice_status(s, "building")
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="timeline"' in body
    assert 'class="tl-node"' in body      # a node marker per activity row


@pytest.mark.django_db
def test_slice_activity_helper_is_chronological_and_scoped(workspace):
    from tuckit.core.services.activity import slice_activity
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice, set_slice_status
    a = create_area(workspace, "Backend")
    s = create_slice(a, "A", status="idea")
    set_slice_status(s, "building")
    other = create_slice(a, "B", status="idea")              # unrelated slice's events excluded
    events = slice_activity(s)
    times = [e.created_at for e in events]
    assert times == sorted(times) and len(events) >= 2        # oldest-first
    assert all(not (e.target_type == "slice" and e.target_id == other.id) for e in events)
