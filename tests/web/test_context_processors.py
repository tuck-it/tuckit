import pytest
from django.test import override_settings

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.plans import create_plan
from tuckit.web.context_processors import auth_chrome
from tuckit.core.services.slices import create_slice


@pytest.fixture
def owner_with_area(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    create_area(org, "Backend")
    client.force_login(owner)
    session = client.session
    session["active_org_id"] = org.id
    session.save()
    return client, org


@pytest.mark.django_db
def test_sidebar_areas_visible_on_org_only_settings_page(owner_with_area):
    """<org_slug>/ (org home) must still resolve the org via the same
    session/first-accessible fallback the org switcher itself uses —
    otherwise the sidebar shows an org name but an empty Areas list."""
    client, org = owner_with_area
    body = client.get(f"/{org.slug}/").content.decode()
    assert "Backend" in body


@pytest.mark.django_db
def test_sidebar_areas_visible_on_account_settings_page(owner_with_area):
    client, org = owner_with_area
    body = client.get(f"/{org.slug}/settings/account/profile").content.decode()
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
def test_onboarding_hidden_stays_hidden_after_area_deleted(client_local, org):
    from tuckit.core.models import ActivityEvent
    from tuckit.core.services.areas import delete_area
    area = create_area(org, "Backend")
    sl = create_slice(area, "Retry webhooks", status="planned")
    p = create_plan(sl, title="Plan")
    create_bite(p, "Add backoff")
    ActivityEvent.objects.create(
        org=org, actor="agent", verb="created",
        target_type="slice", target_id=sl.id, target_label=sl.title,
    )
    p = f"/{org.slug}"
    # First load observes completion → sticky flag set.
    assert "Get started" not in client_local.get(f"{p}/").content.decode()
    org.refresh_from_db()
    assert org.onboarding_completed is True
    # Delete the only Area → has_area now False, but widget must NOT return.
    delete_area(area)
    assert "Get started" not in client_local.get(f"{p}/").content.decode()


@pytest.mark.django_db
def test_onboarding_context_present_on_non_home_page(client_local, org):
    p = f"/{org.slug}"
    assert "Get started" in client_local.get(f"{p}/inbox/").content.decode()


@pytest.mark.django_db
def test_onboarding_short_circuits_when_completed_or_dismissed(rf, org):
    """Once an org is completed or dismissed, the widget can never show
    again, so the processor must bail out before running onboarding_state's
    ~6 queries (or the baseline query) at all."""
    from django.test.utils import CaptureQueriesContext
    from django.db import connection
    from tuckit.web.context_processors import onboarding

    for flag in ("onboarding_completed", "onboarding_dismissed"):
        setattr(org, flag, True)
        org.save(update_fields=[flag])

        request = rf.get("/")
        request.org = org
        request.user = type("Anon", (), {"is_authenticated": False})()

        with CaptureQueriesContext(connection) as ctx:
            result = onboarding(request)

        assert result == {}
        assert len(ctx.captured_queries) == 0

        setattr(org, flag, False)
        org.save(update_fields=[flag])
