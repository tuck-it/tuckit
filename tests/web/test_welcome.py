import pytest
from django.test import override_settings

from tuckit.core.models import ApiToken, User, ActivityEvent, Slice, Area


@pytest.mark.django_db
def test_welcome_renders_standalone_for_logged_in_user(client_local):
    body = client_local.get("/welcome/").content.decode()
    assert '<html lang="en"' in body
    assert "web/welcome.css" in body
    assert "web/app.css" not in body           # standalone, no app shell
    assert "Nothing your agent does" in body   # emotional hero
    assert "/mcp" in body                       # endpoint present


@pytest.mark.django_db
def test_generate_key_creates_one_token_and_reveals_once(client_local, workspace):
    # NOTE: the web `workspace`/`client_local` fixtures bootstrap a token already,
    # so assert an INCREMENT of exactly one, not an absolute count of 0/1.
    before = ApiToken.objects.filter(workspace=workspace).count()
    resp = client_local.post("/welcome/key")
    assert resp.status_code == 200
    assert ApiToken.objects.filter(workspace=workspace).count() == before + 1
    # raw token revealed in the returned fragment
    assert "Bearer" in resp.content.decode()


@pytest.mark.django_db
@override_settings(REGISTRATION_OPEN=True)
def test_signup_redirects_to_welcome(client):
    resp = client.post("/register/", {
        "email": "new@x.com", "org_name": "NewCo", "slug": "newco", "password": "pw123456",
    })
    assert resp.status_code == 302
    assert resp["Location"].endswith("/welcome/")


@pytest.mark.django_db
def test_agent_check_waits_then_celebrates(client_local, workspace):
    # no agent activity yet → 204
    r = client_local.get("/welcome/agent-activity?since=0")
    assert r.status_code == 204
    # an agent write appears
    ev = ActivityEvent.objects.create(
        workspace=workspace, actor="agent", verb="created",
        target_type="slice", target_id=1, target_label="Draft onboarding checklist",
    )
    r = client_local.get("/welcome/agent-activity?since=0")
    assert r.status_code == 200
    assert "Draft onboarding checklist" in r.content.decode()


@pytest.mark.django_db
def test_agent_check_ignores_human_and_old_events(client_local, workspace):
    old = ActivityEvent.objects.create(
        workspace=workspace, actor="agent", verb="created",
        target_type="slice", target_id=1, target_label="old",
    )
    # a later human event must NOT celebrate
    ActivityEvent.objects.create(
        workspace=workspace, actor="human", verb="created",
        target_type="slice", target_id=2, target_label="mine",
    )
    r = client_local.get(f"/welcome/agent-activity?since={old.id}")
    assert r.status_code == 204
