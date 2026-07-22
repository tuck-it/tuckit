import pytest



@pytest.mark.django_db
def test_home_returns_200_and_shell(client_local, org):
    p = f"/{org.slug}"
    resp = client_local.get(f"{p}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "tuckit" in body            # brand in sidebar
    assert "tokens.brand.css" in body and "tokens.product.css" in body


@pytest.mark.django_db
def test_current_org_resolves(client_local, org):
    from tuckit.web.auth import get_current_org

    p = f"/{org.slug}"
    resp = client_local.get(f"{p}/")
    assert get_current_org(resp.wsgi_request).id == org.id


@pytest.mark.django_db
def test_sidebar_shows_icons_and_inbox_count(client_local, org):
    from tuckit.core.services.tickets import create_ticket
    create_ticket(org, "Uncategorized 1")
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert "<svg" in body                 # line icons present
    assert 'class="nav-count"' in body    # inbox count element rendered


@pytest.mark.django_db
def test_sidebar_grouped_with_english_labels_and_capture(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'class="nav-group"' in body        # grouped, not a flat list
    assert 'class="capture-btn"' in body       # Capture promoted to its own button
    assert ">Home<" in body and ">Inbox<" in body and ">Settings<" in body
    assert f'href="{p}/inbox/"' in body             # Inbox anchor keeps the route
    assert ">Board<" in body                         # was Roadmap
    assert ">Attention<" not in body and ">In Progress<" not in body
    assert 'class="nav-sep"' in body        # visual group separator present


@pytest.mark.django_db
def test_sidebar_inbox_count_and_no_lens_tabs(client_local, org):
    from tuckit.core.services.tickets import create_ticket
    create_ticket(org, "Uncategorized")
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert ">Inbox<" in body
    assert 'id="ticket-count"' in body                       # inbox count badge kept
    assert f'href="{p}/attention/"' not in body               # lens tabs gone from nav
    assert f'href="{p}/in-progress/"' not in body
