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
