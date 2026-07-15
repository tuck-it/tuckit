import pytest
from django.test import override_settings

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.orgs import create_workspace
from tuckit.web.context_processors import auth_chrome


@pytest.fixture
def owner_with_area(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    ws = create_workspace(org, "Board")
    create_area(ws, "Backend")
    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()
    return client, org, ws


@pytest.mark.django_db
def test_sidebar_areas_visible_on_org_only_settings_page(owner_with_area):
    """<org_slug>/ (org home) has no ws_slug in the URL, so TenantMiddleware leaves
    request.workspace None on this route. sidebar_areas (and the sibling
    count context processors) must still resolve a workspace via the same
    session/first-accessible fallback the workspace switcher itself uses —
    otherwise the sidebar shows a workspace name but an empty Areas list."""
    client, org, _ws = owner_with_area
    body = client.get(f"/{org.slug}/").content.decode()
    assert "Backend" in body


@pytest.mark.django_db
def test_sidebar_areas_visible_on_account_settings_page(owner_with_area):
    client, _org, _ws = owner_with_area
    body = client.get("/settings/account").content.decode()
    assert "Backend" in body


@override_settings(REGISTRATION_OPEN=True, TUCKIT_MARKETING_URL="https://tuckit.dev")
def test_auth_chrome_exposes_flags(rf):
    ctx = auth_chrome(rf.get("/login/"))
    assert ctx["registration_open"] is True
    assert ctx["marketing_url"] == "https://tuckit.dev"


@override_settings(REGISTRATION_OPEN=False, TUCKIT_MARKETING_URL="")
def test_auth_chrome_defaults(rf):
    ctx = auth_chrome(rf.get("/login/"))
    assert ctx["registration_open"] is False
    assert ctx["marketing_url"] == ""
