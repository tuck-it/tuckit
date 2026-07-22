import re
from pathlib import Path

import pytest

from tuckit.core.models import Org, OrgMember
from tuckit.web.templatetags.web_extras import icon

APP_CSS = Path(__file__).resolve().parents[2] / "tuckit" / "web" / "static" / "web" / "app.css"


def test_search_and_dots_icons_have_paths():
    assert "<path" in icon("search")
    assert "<path" in icon("dots") or "<circle" in icon("dots")


@pytest.mark.django_db
def test_command_palette_rendered_with_area_rows(client_local, org):
    from tuckit.core.services.areas import create_area
    create_area(org, "Backend")
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert 'id="command-palette"' in body           # overlay present
    assert 'data-label="Backend"' in body           # area is a command row
    assert 'data-label="Home"' in body               # static nav command
    assert "command_palette.js" in body              # component script loaded


@pytest.mark.django_db
def test_top_region_has_workspace_and_search_no_wordmark(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert 'class="side-top"' in body
    assert 'class="ws-switch"' in body          # workspace switcher is at top
    assert 'class="search-pill"' in body        # search pill present
    # the old sidebar wordmark <div class="brand">tuckit</div> is gone
    assert '<div class="brand">tuckit</div>' not in body


@pytest.mark.django_db
def test_areas_group_labeled_primary_group_is_not(client_local, org):
    # The primary nav group carries no label (the "Main" header was removed);
    # only the secondary "Areas" group is labeled.
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert ">Main</div>" not in body
    assert 'class="section area-section"' in body


def test_active_nav_uses_token_soft_fill_no_bar():
    css = APP_CSS.read_text(encoding="utf-8")
    assert "inset 3px 0 0 var(--blue)" not in css    # left accent bar removed
    assert ".nav.nav--active { background: var(--blue-soft);" in css  # soft fill via token
    assert ".nav-count" in css and "var(--blue-soft)" in css  # inbox pill uses token bg


@pytest.mark.django_db
def test_collapse_button_and_toggle_present(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert 'class="side-collapse"' in body
    assert "toggleSidebar()" in body


def test_collapsed_rail_css_present():
    css = APP_CSS.read_text(encoding="utf-8")
    assert "html.sidebar-collapsed .sidebar" in css
    assert "@media (min-width: 768px)" in css       # desktop-scoped so mobile drawer is unaffected


@pytest.mark.django_db
def test_areas_header_add_and_row_menu(client_local, org):
    from tuckit.core.services.areas import create_area
    create_area(org, "Backend")
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert 'class="section area-section"' in body      # header row
    assert 'class="area-add-btn"' in body               # + button in header
    assert 'class="area-menu"' in body                  # per-row ⋮ popover
    assert 'class="area-menu-item"' in body             # Rename item in popover
    assert 'class="area-menu-item area-menu-item--danger"' in body  # Delete item wired to area_delete


@pytest.mark.django_db
def test_theme_toggle_is_labeled_row(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
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
def test_resize_handle_rendered(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
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
def test_sidebar_js_loaded_and_width_restored(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert "sidebar.js" in body                 # behavior script loaded
    assert "sidebar-width" in body              # pre-paint restore reads the key


def test_sidebar_js_clamps_to_bounds():
    js = SIDEBAR_JS.read_text(encoding="utf-8")
    assert "180" in js and "420" in js          # min/max bounds
    assert "sidebar-width" in js                # persists under this key
    assert "resizing" in js                     # toggles the no-transition drag class


def test_sidebar_js_syncs_aria_valuenow_on_load_and_clamps_persisted_width():
    js = SIDEBAR_JS.read_text(encoding="utf-8")
    # On load, the handle's aria-valuenow is synced to the restored width
    # (the server markup hardcodes 220 and the pre-paint script can't reach
    # the attribute), using the same validated fallback as currentWidth().
    assert 'handle.setAttribute("aria-valuenow", String(currentWidth()))' in js
    # endDrag clamps the persisted value instead of writing it raw.
    assert "clamp(parseInt(getComputedStyle(root).getPropertyValue(\"--sidebar-w\"), 10))" in js


def test_sidebar_and_panel_density_tightened():
    css = APP_CSS.read_text(encoding="utf-8")
    # .sidebar carries an explicit 13px so labels drop from the inherited 16px
    assert re.search(r"\.sidebar\s*\{[^}]*font-size:\s*13px", css), ".sidebar must set font-size: 13px"
    assert "min-height: 32px" in css        # nav/capture rows tightened from 40 (new value)
    assert re.search(r"\.util-btn\s*\{[^}]*min-height:\s*30px", css), ".util-btn must be 30px"
    assert "min-height: 40px" not in css    # no 40px sidebar rows remain
    # slice-panel frame stepped down (reading body untouched)
    assert ".panel-titlebar .panel-title { font-size: 20px;" in css
    assert ".section-label { font-size: 11px;" in css


@pytest.mark.django_db
def test_collapse_button_uses_panel_left_icon(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert 'class="side-collapse"' in body
    assert 'd="M9 3v18"' in body            # panel-left divider line rendered on the collapse button


def test_panel_left_registered_and_rotation_removed():
    from tuckit.web.templatetags.web_extras import _ICON_PATHS
    assert "panel-left" in _ICON_PATHS
    assert "chevron" in _ICON_PATHS         # still used by the workspace switcher
    css = APP_CSS.read_text(encoding="utf-8")
    assert "transform: rotate(180deg)" not in css   # chevron-rotation rule gone


@pytest.mark.django_db
def test_activity_route_and_sidebar_entry_removed(client_local, org):
    p = f"/{org.slug}"
    assert client_local.get(f"{p}/activity/").status_code == 404   # route gone
    body = client_local.get(f"{p}/").content.decode()
    assert 'aria-label="Activity"' not in body                     # no sidebar button
    assert "/activity/" not in body                                # no link anywhere in the shell


def test_activity_icon_removed():
    from tuckit.web.templatetags.web_extras import _ICON_PATHS
    assert "activity" not in _ICON_PATHS


@pytest.mark.django_db
def test_active_item_soft_fill_no_bar_and_main_label_removed(client_local, org):
    css = APP_CSS.read_text(encoding="utf-8")
    # Active item: soft fill kept, left accent bar dropped
    assert "box-shadow: inset 3px 0 0 var(--blue)" not in css
    assert ".nav.nav--active { background: var(--blue-soft);" in css
    # Settings active unified to the same treatment as nav (adds weight)
    assert re.search(r"\.util-btn--active\s*\{[^}]*font-weight:\s*600", css), ".util-btn--active must be bold like nav"
    # "Main" label removed; the "Areas" group label is kept
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert '<div class="section">Main</div>' not in body
    assert 'class="section area-section"' in body


@pytest.mark.django_db
def test_sidebar_areas_label_links_to_overview(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'class="area-section-link"' in body
    assert f'href="/{org.slug}/areas/"' in body


@pytest.mark.django_db
def test_sidebar_areas_active_on_overview(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/areas/").content.decode()
    assert "area-section-link--active" in body


@pytest.mark.django_db
def test_sidebar_settings_opens_settings_mode(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert f'href="/{org.slug}/settings/"' in body


@pytest.mark.django_db
def test_switcher_lists_orgs_flat(client_local, org, django_user_model):
    second = Org.objects.create(name="Second Co", slug="second-co")
    user = django_user_model.objects.get(email="local@tuckit.local")
    OrgMember.objects.create(user=user, org=second, role="owner")

    body = client_local.get(f"/{org.slug}/").content.decode()

    assert f'href="/{second.slug}/"' in body
    assert "ws-menu-org" not in body  # the org-header/regroup row is gone


@pytest.mark.django_db
def test_switcher_footer_links_to_picker(client_local, org):
    assert 'href="/orgs/"' in client_local.get(f"/{org.slug}/").content.decode()


@pytest.mark.django_db
def test_no_breadcrumb_on_any_page(client_local, org):
    for path in ("", "areas/", "roadmap/"):
        body = client_local.get(f"/{org.slug}/{path}").content.decode()
        assert "crumbbar" not in body


@pytest.mark.django_db
def test_sidebar_area_create_has_description_field(client_local, org):
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert 'name="description"' in body   # sidebar "+ Area" create form exposes description


@pytest.mark.django_db
def test_sidebar_shows_signed_in_account(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
    # The account menu trigger lives in the util-row and surfaces the user's email.
    assert 'class="account-menu"' in body
    assert "local@tuckit.local" in body            # signed-in identity is the email
    assert 'class="account-avatar"' in body        # first-letter avatar cue


@pytest.mark.django_db
def test_account_menu_has_settings_link_and_logout_post(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
    # Account settings entry points at the account settings root for this org.
    assert f'href="/{org.slug}/settings/account"' in body
    # Log out MUST be a POST form (Django LogoutView is POST-only) with CSRF.
    assert 'action="/logout/"' in body
    assert re.search(
        r'<form[^>]*action="/logout/"[^>]*method="post"', body
    ) or re.search(r'<form[^>]*method="post"[^>]*action="/logout/"', body)
    assert "csrfmiddlewaretoken" in body


def test_account_menu_css_present():
    css = APP_CSS.read_text(encoding="utf-8")
    assert ".account-menu" in css
    assert ".account-avatar" in css
    # Popup opens upward from the sidebar bottom.
    assert ".account-pop" in css


@pytest.mark.django_db
def test_sidebar_reorder_url_matches_the_routed_url(client_local, org):
    """Same root cause as the board's move URL: area_nav.js hand-built
    /areas/<id>/reorder while the route is org-scoped, so sidebar drag-to-
    reorder 404'd. The URL now comes from the row's data-reorder-url."""
    import re
    from pathlib import Path
    from tuckit.core.services.areas import create_area

    first = create_area(org, "Alpha")
    second = create_area(org, "Beta")

    js = (Path(__file__).resolve().parents[2] / "tuckit" / "web" / "static" / "web" / "area_nav.js").read_text()
    assert 'getAttribute("data-reorder-url")' in js, "area_nav.js must read the URL, not build it"
    assert '"/areas/"' not in js, "area_nav.js is hand-building an org-less reorder URL again"

    body = client_local.get(f"/{org.slug}/").content.decode()
    url = re.search(r'data-reorder-url="([^"]+)"', body).group(1)
    assert url.startswith(f"/{org.slug}/areas/")

    resp = client_local.post(
        f"/{org.slug}/areas/{second.id}/reorder", {"before_id": first.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code in (200, 204), f"sidebar posts to {url!r} -> {resp.status_code}"
