import pytest


@pytest.mark.django_db
def test_sidebar_uses_tuckit_wordmark(client_local, workspace):
    body = client_local.get("/").content.decode()
    assert ">tuckit<" in body
    assert ">tuck-it<" not in body


@pytest.mark.django_db
def test_page_head_present_with_title(client_local, workspace):
    body = client_local.get("/").content.decode()
    assert 'class="page-head"' in body
    assert 'class="page-title"' in body


@pytest.mark.django_db
def test_mobile_topbar_and_menu_present(client_local, workspace):
    body = client_local.get("/").content.decode()
    assert 'class="topbar-mobile"' in body
    # menu toggle has an accessible name
    assert 'aria-label="Open navigation menu"' in body
    # capture reachable from the mobile top bar without opening the menu
    assert 'aria-label="Quick capture"' in body      # capture reachable from top bar
    assert 'x-ref="menuToggle"' in body              # focus-restore target wired
    assert "trapFocus" in body                       # focus trap wired


@pytest.mark.django_db
def test_current_workspace_in_template_context(client_local, workspace):
    resp = client_local.get("/")
    assert resp.context["current_workspace"].id == workspace.id


@pytest.mark.django_db
def test_switchable_workspaces_sorted_by_org_then_name(client_local, workspace):
    resp = client_local.get("/")
    ws = list(resp.context["switchable_workspaces"])
    keys = [(w.org.name, w.name) for w in ws]
    assert keys == sorted(keys)
