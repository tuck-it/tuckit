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


@pytest.mark.django_db
def test_sidebar_areas_keep_rank_order_despite_annotation(client_local, org):
    """The slice_count annotation adds a GROUP BY, and Django does not apply
    Meta.ordering to aggregate queries — so the queryset needs an explicit
    order_by. Without it the SQL has no ORDER BY at all: sqlite happens to
    return rowid order, Postgres guarantees nothing, and the sidebar's
    drag-to-reorder silently stops sticking."""
    from tuckit.core.services.areas import create_area, reorder_area

    first = create_area(org, "Alpha")
    create_area(org, "Beta")
    third = create_area(org, "Gamma")
    # Drag Gamma to the top — the whole point of `rank`. Rank order now differs
    # from insertion order, so a query with no ORDER BY gives itself away.
    reorder_area(third, before=first)

    body = client_local.get(f"/{org.slug}/").content.decode()
    positions = [body.index(name) for name in ("Gamma", "Alpha", "Beta")]
    assert positions == sorted(positions), "sidebar areas are not in rank order"


@pytest.mark.django_db
def test_dead_lens_count_processors_are_gone(client_local, org):
    """attention_count / in_progress_count ran on every request and no template
    ever read them — in_progress_count cost two COUNT queries per request. Their
    absence is the deliverable, so assert they cannot creep back."""
    from tuckit.web import context_processors as cp

    assert not hasattr(cp, "attention_count")
    assert not hasattr(cp, "in_progress_count")

    resp = client_local.get(f"/{org.slug}/")
    assert resp.status_code == 200
    assert "attention_count" not in resp.context
    assert "in_progress_count" not in resp.context
