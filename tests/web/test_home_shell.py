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
    assert body.count("cap = true") >= 3
