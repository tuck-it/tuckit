import pytest

from tuckit.core.models import ActivityEvent, ApiToken


@pytest.mark.django_db
def test_connect_key_creates_token_and_shows_snippet(client_local, org):
    p = f"/{org.slug}"
    r = client_local.post(f"{p}/onboarding/connect-key")
    assert r.status_code == 200
    assert ApiToken.objects.filter(org=org, name="Agent (onboarding)").exists()
    body = r.content.decode()
    assert "MCP endpoint" in body
    assert "claude mcp add" in body        # Claude Code snippet
    assert 'id="gs-listen"' in body        # poller included


@pytest.mark.django_db
def test_agent_check_waiting_returns_poller(client_local, org):
    p = f"/{org.slug}"
    r = client_local.get(f"{p}/onboarding/agent-activity?since=0")
    assert r.status_code == 200
    assert 'id="gs-listen"' in r.content.decode()   # keeps polling, not 204


@pytest.mark.django_db
def test_agent_check_celebrates_on_agent_event(client_local, org):
    ActivityEvent.objects.create(
        org=org, source="agent", verb="created",
        target_type="slice", target_id=1, target_label="Retry webhooks",
    )
    p = f"/{org.slug}"
    r = client_local.get(f"{p}/onboarding/agent-activity?since=0")
    assert r.status_code == 200
    body = r.content.decode()
    assert "Retry webhooks" in body                 # celebrate fragment
    assert 'id="gs-listen"' not in body             # polling stops
