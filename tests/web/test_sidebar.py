import re
from pathlib import Path

import pytest

from tuckit.web.templatetags.web_extras import icon

APP_CSS = Path(__file__).resolve().parents[2] / "tuckit" / "web" / "static" / "web" / "app.css"


def test_search_and_dots_icons_have_paths():
    assert "<path" in icon("search")
    assert "<path" in icon("dots") or "<circle" in icon("dots")


@pytest.mark.django_db
def test_command_palette_rendered_with_area_rows(client_local, workspace):
    from tuckit.core.services.areas import create_area
    create_area(workspace, "Backend")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'id="command-palette"' in body           # overlay present
    assert 'data-label="Backend"' in body           # area is a command row
    assert 'data-label="Home"' in body               # static nav command
    assert "command_palette.js" in body              # component script loaded


@pytest.mark.django_db
def test_top_region_has_workspace_and_search_no_wordmark(client_local, workspace):
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="side-top"' in body
    assert 'class="ws-switch"' in body          # workspace switcher is at top
    assert 'class="search-pill"' in body        # search pill present
    # the old sidebar wordmark <div class="brand">tuckit</div> is gone
    assert '<div class="brand">tuckit</div>' not in body


@pytest.mark.django_db
def test_main_section_header_present(client_local, workspace):
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert ">Main</div>" in body


def test_active_nav_has_accent_bar_via_token():
    css = APP_CSS.read_text(encoding="utf-8")
    assert "inset 3px 0 0 var(--blue)" in css       # accent bar, token color
    assert ".nav-count" in css and "var(--blue-soft)" in css  # inbox pill uses token bg


@pytest.mark.django_db
def test_collapse_button_and_toggle_present(client_local, workspace):
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="side-collapse"' in body
    assert "toggleSidebar()" in body


def test_collapsed_rail_css_present():
    css = APP_CSS.read_text(encoding="utf-8")
    assert "html.sidebar-collapsed .sidebar" in css
    assert "@media (min-width: 768px)" in css       # desktop-scoped so mobile drawer is unaffected


@pytest.mark.django_db
def test_areas_header_add_and_row_menu(client_local, workspace):
    from tuckit.core.services.areas import create_area
    create_area(workspace, "Backend")
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="section area-section"' in body      # header row
    assert 'class="area-add-btn"' in body               # + button in header
    assert 'class="area-menu"' in body                  # per-row ⋮ popover
    assert 'class="area-menu-item"' in body             # Rename item in popover
    assert 'class="area-menu-item area-menu-item--danger"' in body  # Delete item wired to area_delete


@pytest.mark.django_db
def test_theme_toggle_is_labeled_row(client_local, workspace):
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert "util-theme" in body
    assert "util-theme-label" in body     # promoted to a labeled row


def test_new_sidebar_css_uses_no_raw_hex():
    css = APP_CSS.read_text(encoding="utf-8")
    # No 3/6-digit hex color literals anywhere in the components file.
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
    assert hexes == [], f"app.css must use var(--token), found hex: {hexes}"


def test_sidebar_shell_is_pinned_and_width_variable():
    css = APP_CSS.read_text(encoding="utf-8")
    # Viewport-pinned, self-scrolling shell
    assert "position: sticky" in css
    assert "100dvh" in css
    assert "overflow-y: auto" in css
    # Width driven by a variable with an animated flex-basis
    assert "--sidebar-w: 220px" in css            # :root default
    assert "var(--sidebar-w, 220px)" in css        # consumed by .sidebar
    assert "transition: flex-basis" in css


def test_collapse_animates_and_keeps_chevron_on_top():
    css = APP_CSS.read_text(encoding="utf-8")
    # Collapse overrides the width variable (so flex-basis transition animates it)
    assert "html.sidebar-collapsed .sidebar { --sidebar-w: 60px; }" in css
    # Old instant flex-basis swap is gone
    assert "html.sidebar-collapsed .sidebar { flex-basis: 60px; }" not in css
    # Chevron is pulled to the top of the collapsed column
    assert "html.sidebar-collapsed .side-collapse { order: -1; }" in css


@pytest.mark.django_db
def test_resize_handle_rendered(client_local, workspace):
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert 'class="side-resize"' in body
    assert 'role="separator"' in body
    assert 'aria-orientation="vertical"' in body


def test_resize_handle_css_present():
    css = APP_CSS.read_text(encoding="utf-8")
    assert ".side-resize" in css
    assert "col-resize" in css                       # resize cursor
    assert "html.resizing .sidebar { transition: none; }" in css   # 1:1 tracking
    assert "html.sidebar-collapsed .side-resize { display: none; }" in css  # hidden collapsed


SIDEBAR_JS = APP_CSS.parent / "sidebar.js"


@pytest.mark.django_db
def test_sidebar_js_loaded_and_width_restored(client_local, workspace):
    body = client_local.get(f"/{workspace.org.slug}/{workspace.slug}/").content.decode()
    assert "sidebar.js" in body                 # behavior script loaded
    assert "sidebar-width" in body              # pre-paint restore reads the key


def test_sidebar_js_clamps_to_bounds():
    js = SIDEBAR_JS.read_text(encoding="utf-8")
    assert "180" in js and "420" in js          # min/max bounds
    assert "sidebar-width" in js                # persists under this key
    assert "resizing" in js                     # toggles the no-transition drag class
