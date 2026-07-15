import pytest
from django.test import override_settings

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.orgs import create_workspace
from tuckit.web.context_processors import auth_chrome
from tuckit.core.services.slices import create_slice


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
    """settings/<org_slug>/ has no ws_slug in the URL, so TenantMiddleware leaves
    request.workspace None on this route. sidebar_areas (and the sibling
    count context processors) must still resolve a workspace via the same
    session/first-accessible fallback the workspace switcher itself uses —
    otherwise the sidebar shows a workspace name but an empty Areas list."""
    client, org, _ws = owner_with_area
    body = client.get(f"/settings/{org.slug}/").content.decode()
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
@pytest.mark.django_db
def test_onboarding_hidden_stays_hidden_after_area_deleted(client_local, workspace):
    from tuckit.core.models import ActivityEvent
    from tuckit.core.services.areas import delete_area
    area = create_area(workspace, "Backend")
    sl = create_slice(area, "Retry webhooks", status="planned")
    create_bite(sl, "Add backoff")
    ActivityEvent.objects.create(
        workspace=workspace, actor="agent", verb="created",
        target_type="slice", target_id=sl.id, target_label=sl.title,
    )
    p = f"/{workspace.org.slug}/{workspace.slug}"
    # First load observes completion → sticky flag set.
    assert "Get started" not in client_local.get(f"{p}/").content.decode()
    workspace.refresh_from_db()
    assert workspace.onboarding_completed is True
    # Delete the only Area → has_area now False, but widget must NOT return.
    delete_area(area)
    assert "Get started" not in client_local.get(f"{p}/").content.decode()


@pytest.mark.django_db
def test_onboarding_context_present_on_non_home_page(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    assert "Get started" in client_local.get(f"{p}/triage/").content.decode()


@pytest.mark.django_db
def test_onboarding_short_circuits_when_completed_or_dismissed(rf, workspace):
    """Once a workspace is completed or dismissed, the widget can never show
    again, so the processor must bail out before running onboarding_state's
    ~6 queries (or the baseline query) at all."""
    from django.test.utils import CaptureQueriesContext
    from django.db import connection
    from tuckit.web.context_processors import onboarding

    for flag in ("onboarding_completed", "onboarding_dismissed"):
        setattr(workspace, flag, True)
        workspace.save(update_fields=[flag])

        request = rf.get("/")
        request.workspace = workspace
        request.user = type("Anon", (), {"is_authenticated": False})()

        with CaptureQueriesContext(connection) as ctx:
            result = onboarding(request)

        assert result == {}
        assert len(ctx.captured_queries) == 0

        setattr(workspace, flag, False)
        workspace.save(update_fields=[flag])
