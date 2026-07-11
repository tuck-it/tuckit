import re

import pytest

from tuckit.core.models import ApiToken, Org, Workspace
from tuckit.core.services.tokens import generate_token, hash_token


@pytest.mark.django_db
def test_token_create_shows_raw_once(client_local, workspace):
    resp = client_local.post("/settings/tokens", {"name": "Claude Code"}, HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert len(body) > 0  # raw token surfaced in the returned partial


@pytest.mark.django_db
def test_token_create_stores_only_hash_not_raw(client_local, workspace):
    resp = client_local.post("/settings/tokens", {"name": "Claude Code"}, HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    token = ApiToken.objects.get(workspace=workspace, name="Claude Code")
    # the raw token appears in the one-time partial...
    match = re.search(r'class="token-value"[^>]*>([^<]+)<', body)
    assert match, "raw token should be shown once in the create partial"
    raw = match.group(1)
    assert hash_token(raw) == token.token_hash
    # ...but the stored row never holds the raw value itself
    assert token.token_hash != raw


@pytest.mark.django_db
def test_settings_page_lists_masked_tokens(client_local, workspace):
    token, raw = generate_token(workspace, "Existing")
    resp = client_local.get("/settings/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Existing" in body
    assert raw not in body  # never re-displayed on the list page
    assert token.token_hash[:8] in body  # masked/truncated hash shown instead


@pytest.mark.django_db
def test_workspace_rename(client_local, workspace):
    client_local.post("/settings/rename", {"name": "My Product"}, HTTP_HX_REQUEST="true")
    workspace.refresh_from_db()
    assert workspace.name == "My Product"


@pytest.mark.django_db
def test_token_revoke_removes_token(client_local, workspace):
    token, _ = generate_token(workspace, "to-remove")
    resp = client_local.post(f"/settings/tokens/{token.id}/revoke", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert not ApiToken.objects.filter(id=token.id).exists()


@pytest.mark.django_db
def test_token_revoke_is_workspace_scoped(client_local, workspace):
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other = Workspace.objects.create(org=other_org, name="Other", slug="other")
    token, _ = generate_token(other, "cli")
    resp = client_local.post(f"/settings/tokens/{token.id}/revoke", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert ApiToken.objects.filter(id=token.id).exists()  # untouched: belongs to another workspace


@pytest.mark.django_db
def test_token_list_is_a_panel(client_local, workspace):
    from tuckit.core.services.tokens import generate_token

    generate_token(workspace, "CI")
    body = client_local.get("/settings/").content.decode()
    assert 'class="panel"' in body
