from pathlib import Path

import pytest

APP_CSS = Path(__file__).resolve().parents[2] / "tuckit" / "web" / "static" / "web" / "app.css"


@pytest.mark.django_db
def test_sidebar_uses_tuckit_wordmark(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert ">tuckit<" in body
    assert ">tuck-it<" not in body


@pytest.mark.django_db
def test_page_head_present_with_title(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'class="page-head"' in body
    assert 'class="page-title"' in body


@pytest.mark.django_db
def test_mobile_topbar_and_menu_present(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'class="topbar-mobile"' in body
    # menu toggle has an accessible name
    assert 'aria-label="Open navigation menu"' in body
    # capture reachable from the mobile top bar without opening the menu
    assert 'aria-label="Quick capture"' in body      # capture reachable from top bar
    assert 'x-ref="menuToggle"' in body              # focus-restore target wired
    assert "trapFocus" in body                       # focus trap wired


@pytest.mark.django_db
def test_current_workspace_in_template_context(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    resp = client_local.get(f"{p}/")
    assert resp.context["current_workspace"].id == workspace.id


@pytest.mark.django_db
def test_switchable_workspaces_sorted_by_org_then_name(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    resp = client_local.get(f"{p}/")
    ws = list(resp.context["switchable_workspaces"])
    keys = [(w.org.name, w.name) for w in ws]
    assert keys == sorted(keys)


@pytest.mark.django_db
def test_switcher_is_custom_popover_not_native_select(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'class="ws-switch"' in body            # custom trigger button
    assert 'class="ws-menu"' in body              # popover panel
    assert '<select name="workspace_id"' not in body   # native 2001 dropdown gone
    assert f'href="{p}/"' in body                 # switch target: workspace deep-link
    assert 'class="ws-menu-item' in body          # switch entries render as popover menu items


@pytest.mark.django_db
def test_nav_order_queues_before_states_activity_last(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    i_att = body.find(">Attention<")
    i_tri = body.find(">Triage<")
    i_prog = body.find(">In Progress<")
    i_road = body.find(">Roadmap<")
    i_act = body.find(">Activity<")
    assert -1 not in (i_att, i_tri, i_prog, i_road, i_act)
    assert i_att < i_tri < i_prog < i_road < i_act


@pytest.mark.django_db
def test_bottom_utility_row_replaces_bordered_theme_button(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'class="util-row"' in body                 # compact icon row present
    assert "theme-toggle" not in body                 # old bordered button gone
    assert ">Light mode<" not in body                 # text label gone
    assert ">Dark mode<" not in body
    assert "Switch to light mode" in body             # icon toggle keeps an accessible name


@pytest.mark.django_db
def test_capture_button_still_rendered(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'class="capture-btn"' in body


def test_capture_button_is_solid_teal_primary():
    css = APP_CSS.read_text(encoding="utf-8")
    block = css.split(".capture-btn {", 1)[1].split("}", 1)[0]
    assert "background: var(--blue)" in block   # solid teal, not paper-raised
    assert "border: none" in block              # mismatched border removed
