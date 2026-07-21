import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite
from tuckit.core.services.plans import create_plan


def _p(org):
    return f"/{org.slug}"


@pytest.mark.django_db
def test_widget_shows_five_steps_on_fresh_home(client_local, org):
    body = client_local.get(f"{_p(org)}/").content.decode()
    assert 'id="onboarding-widget"' in body
    assert "Create your first Area" in body
    assert "Add your first Slice" in body
    assert "Add a Plan" in body
    assert "Break it into Bites" in body
    assert "Connect your agent" in body
    assert "/5" in body  # step counter
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
def test_widget_slice_step_opens_area_scoped_modal(client_local, org):
    a = create_area(org, "Backend")
    body = client_local.get(f"{_p(org)}/").content.decode()
    # Slice step opens an in-widget modal that creates a slice in the newest area.
    assert f"/areas/{a.slug}/slices" in body
    assert "Create a new Slice" in body
    assert "in <strong>Backend</strong>" in body


@pytest.mark.django_db
def test_slice_modal_teaches_what_a_slice_is(client_local, org):
    # With an Area but no Slice, the widget's slice modal is rendered. It must
    # explain what a slice is and show an example in the title placeholder —
    # obvious fields (Area/Status/Tags) stay unadorned.
    create_area(org, "Backend")
    body = client_local.get(f"{_p(org)}/").content.decode()
    assert "One shippable chunk of product work in <strong>Backend</strong>" in body
    assert "Retry failed webhooks" in body  # example in the title placeholder
    # the shared spec field teaches what to write, with an example
    assert "The what &amp; why" in body
    assert "exponential backoff" in body


@pytest.mark.django_db
def test_widget_plan_step_links_to_newest_slice(client_local, org):
    area = create_area(org, "Backend")
    sl = create_slice(area, "Retry webhooks", status="planned")
    body = client_local.get(f"/{org.slug}/").content.decode()
    # With a Slice but no Plan, the current step is Add-a-Plan → ?focus=plan.
    assert f"/slices/{sl.id}/?focus=plan" in body


@pytest.mark.django_db
def test_widget_bite_step_links_after_plan_exists(client_local, org):
    from tuckit.core.services.plans import create_plan
    area = create_area(org, "Backend")
    sl = create_slice(area, "Retry webhooks", status="planned")
    create_plan(sl, title="Plan")
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
    # Reach step 5 (onboarding.current == 5) by completing area/slice/plan/bite
    # first — the widget only renders the connect UI once current == 5.
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
    # Primary onboarding poller now uses a distinct id (ob-listen) so it can't
    # collide with the headless fallback's own poller (gs-listen).
    assert 'id="ob-listen"' in body
    assert "/onboarding/agent-activity" in body


@pytest.mark.django_db
def test_onboarding_step1_has_description_field(client_local, org):
    # Fresh org (no non-triage areas) => Step 1 is active with the create form rendered.
    import re
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert 'id="onboarding-widget"' in body
    # Step 1 opens the shared Area-create modal (also used by the sidebar/areas page).
    m = re.search(r'<form class="[^"]*area-create-form[^"]*".*?</form>', body, re.S)
    assert m is not None
    form = m.group(0)
    assert 'name="name"' in form
    assert 'name="description"' in form          # description is a first-class labeled field
    assert "Create a new Area" in form           # deliberate, titled modal (not a bare input)


@pytest.mark.django_db
def test_step5_leads_with_tokenless_oauth_and_live_poller(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a, "Retry webhooks")
    pl = create_plan(s, title="v1")
    create_bite(pl, "wire it")  # now at step 5 (all prior steps done, not connected)
    body = client_local.get(f"{_p(org)}/").content.decode()
    # tokenless command is the headline; no raw-token instruction up front
    assert "claude mcp add --transport http tuckit" in body
    assert "Authorization: Bearer" not in body   # no raw-token command on the page
    # the live poller starts immediately, without generating a key
    assert 'id="ob-listen"' in body
    # key-gen demoted into a headless fallback disclosure
    assert "<details" in body
    assert "Generate agent key" in body
    assert "No browser" in body
    # other clients point to the canonical settings switcher
    assert "/settings/agent" in body


@pytest.mark.django_db
def test_step5_poller_has_distinct_id_no_collision_with_fallback(client_local, org):
    # The primary poller must use a distinct id (ob-listen) from the
    # fallback's poller (gs-listen, rendered only after key-gen). Before the
    # fix both instances shared id="gs-listen", so htmx's self-referencing
    # hx-target="#gs-listen" resolved to the first match and the fallback
    # poller became a zombie that never got replaced.
    a = create_area(org, "Backend")
    s = create_slice(a, "Retry webhooks")
    pl = create_plan(s, title="v1")
    create_bite(pl, "wire it")  # now at step 5
    body = client_local.get(f"{_p(org)}/").content.decode()
    assert 'id="ob-listen"' in body
    assert 'id="gs-listen"' not in body  # fallback poller not rendered until key-gen runs
