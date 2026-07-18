import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite
from tuckit.core.services.plans import create_plan


def _p(org):
    return f"/{org.slug}"


@pytest.mark.django_db
def test_widget_shows_four_steps_on_fresh_home(client_local, org):
    body = client_local.get(f"{_p(org)}/").content.decode()
    assert 'id="onboarding-widget"' in body
    assert "Create your first Area" in body
    assert "Add your first Slice" in body
    assert "Break it into Bites" in body
    assert "Connect your agent" in body
    # a11y: disclosure toggle points at the collapsible body, decorative
    # checkmark glyphs are hidden from assistive tech.
    assert 'aria-controls="ob-body"' in body
    assert 'id="ob-body"' in body
    assert 'class="ob-box" aria-hidden="true"' in body


@pytest.mark.django_db
def test_widget_area_step_posts_to_real_endpoint(client_local, org):
    # Area is created inline in the widget via the REAL area_create endpoint.
    body = client_local.get(f"{_p(org)}/").content.decode()
    assert "/areas/new" in body  # web:area_create target
    assert "/onboarding/area" not in body  # bespoke endpoint retired


@pytest.mark.django_db
def test_widget_slice_step_links_to_real_area_page(client_local, org):
    create_area(org, "Backend")
    body = client_local.get(f"{_p(org)}/").content.decode()
    # Slice step deep-links into the real Area page with a focus hint.
    assert "focus=slice" in body


@pytest.mark.django_db
def test_widget_bite_step_links_to_real_slice(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    area = create_area(org, "Backend")
    sl = create_slice(area, "Retry webhooks", status="idea")
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert f"/slices/{sl.id}/?focus=bite" in body


@pytest.mark.django_db
def test_widget_hidden_when_all_done(client_local, org):
    from tuckit.core.models import ActivityEvent
    area = create_area(org, "Backend")
    sl = create_slice(area, "Retry webhooks", status="planned")
    create_bite(create_plan(sl, title="Plan"), "Add backoff")
    ActivityEvent.objects.create(
        org=org, actor="agent", verb="created",
        target_type="slice", target_id=sl.id, target_label=sl.title,
    )
    body = client_local.get(f"{_p(org)}/").content.decode()
    assert 'id="onboarding-widget"' not in body


@pytest.mark.django_db
def test_dismiss_hides_widget(client_local, org):
    p = _p(org)
    r = client_local.post(f"{p}/onboarding/dismiss")
    assert r.status_code in (200, 204, 302)
    org.refresh_from_db()
    assert org.onboarding_dismissed is True
    assert 'id="onboarding-widget"' not in client_local.get(f"{p}/").content.decode()


@pytest.mark.django_db
def test_step4_shows_generate_key_when_no_key(client_local, org):
    # Reach step 4 (onboarding.current == 4) by completing area/slice/bite first —
    # the widget only renders the connect UI once current == 4.
    area = create_area(org, "Backend")
    sl = create_slice(area, "Retry webhooks", status="planned")
    create_bite(create_plan(sl, title="Plan"), "Add backoff")
    body = client_local.get(f"{_p(org)}/").content.decode()
    assert "/onboarding/connect-key" in body
    assert "/welcome/" not in body


@pytest.mark.django_db
def test_step4_shows_poller_when_key_exists(client_local, org):
    from tuckit.core.models import ApiToken
    area = create_area(org, "Backend")
    sl = create_slice(area, "Retry webhooks", status="planned")
    create_bite(create_plan(sl, title="Plan"), "Add backoff")
    ApiToken.objects.create(org=org, name="a", token_hash="x")
    body = client_local.get(f"{_p(org)}/").content.decode()
    assert 'id="gs-listen"' in body
    assert "/onboarding/agent-activity" in body


@pytest.mark.django_db
def test_onboarding_step1_has_description_field(client_local, org):
    # Fresh org (no non-triage areas) => Step 1 is active with the create form rendered.
    import re
    body = client_local.get(f"/{org.slug}/triage/").content.decode()
    assert 'id="onboarding-widget"' in body
    # Scope to the onboarding Step-1 form so we don't match the sidebar create form.
    m = re.search(r'<form class="ob-form".*?</form>', body, re.S)
    assert m is not None
    assert 'name="description"' in m.group(0)   # Step 1 exposes description via the shared partial
