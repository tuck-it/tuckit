import pytest


@pytest.mark.django_db
def test_home_returns_200_and_shell(client_local):
    resp = client_local.get("/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "tuck-it" in body            # brand in sidebar
    assert "/static/web/tokens.css" in body or "tokens.css" in body


@pytest.mark.django_db
def test_current_workspace_resolves(client_local, workspace):
    from tuckit.web.auth import get_current_workspace

    resp = client_local.get("/")
    assert get_current_workspace(resp.wsgi_request).id == workspace.id


@pytest.mark.django_db
def test_sidebar_shows_icons_and_inbox_count(client_local, workspace):
    from tuckit.core.services.areas import get_or_create_inbox
    from tuckit.core.services.slices import create_slice
    create_slice(get_or_create_inbox(workspace), "미분류 1")
    body = client_local.get("/").content.decode()
    assert "<svg" in body                 # line icons present
    assert 'class="nav-count"' in body    # inbox count element rendered
