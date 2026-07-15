import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite


@pytest.mark.django_db
def test_checklist_shows_four_steps_on_fresh_home(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert "Get started" in body
    assert "Create your first Area" in body
    assert "Add your first Slice" in body
    assert "Break it into Bites" in body
    assert "Connect your agent" in body


@pytest.mark.django_db
def test_fresh_home_gates_slice_step(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    # no Area yet → the Slice step shows the gate hint, not a create form
    assert "Create an Area first." in body


@pytest.mark.django_db
def test_slice_form_appears_after_area(client_local, workspace):
    create_area(workspace, "Backend")
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert "/onboarding/slice" in body
    assert "Create an Area first." not in body


@pytest.mark.django_db
def test_checklist_hidden_when_all_done(client_local, workspace):
    from tuckit.core.models import ActivityEvent
    area = create_area(workspace, "Backend")
    sl = create_slice(area, "Retry webhooks", status="planned")
    create_bite(sl, "Add backoff")
    ActivityEvent.objects.create(
        workspace=workspace, actor="agent", verb="created",
        target_type="slice", target_id=sl.id, target_label=sl.title,
    )
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert "Get started" not in body


@pytest.mark.django_db
def test_dismiss_hides_checklist(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    r = client_local.post(f"{p}/onboarding/dismiss")
    assert r.status_code in (200, 204, 302)
    workspace.refresh_from_db()
    assert workspace.onboarding_dismissed is True
    assert "Get started" not in client_local.get(f"{p}/").content.decode()


@pytest.mark.django_db
def test_checklist_above_needs_you_when_no_area(client_local, workspace):
    # Fresh workspace (only Triage, no Area) → checklist is the hero, above needs_you
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert body.index("Get started") < body.index("needs_you")


@pytest.mark.django_db
def test_checklist_below_needs_you_once_area_exists(client_local, workspace):
    create_area(workspace, "Backend")  # has_area True, still onboarding
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert body.index("needs_you") < body.index("Get started")


@pytest.mark.django_db
def test_step4_shows_generate_key_when_no_key(client_local, workspace):
    create_area(workspace, "Backend")  # so checklist shows and step 4 reachable
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert "/onboarding/connect-key" in body     # generate button target
    assert "/welcome/" not in body               # no link out to the old page


@pytest.mark.django_db
def test_home_connect_step_renders_mcp_endpoint(client_local, workspace):
    # fresh workspace (not connected) → the connect card shows the real MCP endpoint value
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert "http://testserver/mcp" in body


@pytest.mark.django_db
def test_step4_shows_poller_when_key_exists(client_local, workspace):
    from tuckit.core.models import ApiToken
    ApiToken.objects.create(workspace=workspace, name="a", token_hash="x")
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'id="gs-listen"' in body              # listening/poller state
    assert "/onboarding/agent-activity" in body
