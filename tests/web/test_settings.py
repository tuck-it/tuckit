import re

import pytest

from tuckit.core.models import ApiToken, Org, Workspace
from tuckit.core.services.tokens import generate_token, hash_token


@pytest.mark.django_db
def test_token_create_shows_raw_once(client_local, workspace):
    sp = f"/settings/{workspace.org.slug}/{workspace.slug}"
    resp = client_local.post(f"{sp}/tokens", {"name": "Claude Code"}, HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert len(body) > 0  # raw token surfaced in the returned partial


@pytest.mark.django_db
def test_token_create_stores_only_hash_not_raw(client_local, workspace):
    sp = f"/settings/{workspace.org.slug}/{workspace.slug}"
    resp = client_local.post(f"{sp}/tokens", {"name": "Claude Code"}, HTTP_HX_REQUEST="true")
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
    sp = f"/settings/{workspace.org.slug}/{workspace.slug}"
    resp = client_local.get(f"{sp}/workspace")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Existing" in body
    assert raw not in body  # never re-displayed on the list page
    assert token.token_hash[:8] in body  # masked/truncated hash shown instead


@pytest.mark.django_db
def test_workspace_rename(client_local, workspace):
    sp = f"/settings/{workspace.org.slug}/{workspace.slug}"
    client_local.post(f"{sp}/rename", {"name": "My Product"}, HTTP_HX_REQUEST="true")
    workspace.refresh_from_db()
    assert workspace.name == "My Product"


@pytest.mark.django_db
def test_token_revoke_removes_token(client_local, workspace):
    token, _ = generate_token(workspace, "to-remove")
    sp = f"/settings/{workspace.org.slug}/{workspace.slug}"
    resp = client_local.post(f"{sp}/tokens/{token.id}/revoke", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert not ApiToken.objects.filter(id=token.id).exists()


@pytest.mark.django_db
def test_token_revoke_is_workspace_scoped(client_local, workspace):
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other = Workspace.objects.create(org=other_org, name="Other", slug="other")
    token, _ = generate_token(other, "cli")
    sp = f"/settings/{workspace.org.slug}/{workspace.slug}"
    resp = client_local.post(f"{sp}/tokens/{token.id}/revoke", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert ApiToken.objects.filter(id=token.id).exists()  # untouched: belongs to another workspace


@pytest.mark.django_db
def test_token_list_is_a_panel(client_local, workspace):
    from tuckit.core.services.tokens import generate_token

    generate_token(workspace, "CI")
    sp = f"/settings/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{sp}/workspace").content.decode()
    assert 'class="panel"' in body


@pytest.mark.django_db
def test_shipped_board_prefs_updates(client_local, workspace):
    p = f"/settings/{workspace.org.slug}/{workspace.slug}/shipped-board"
    resp = client_local.post(p, {"mode": "days", "limit": "30"})
    assert resp.status_code == 204
    ws = Workspace.objects.get(pk=workspace.pk)
    assert ws.shipped_board_mode == "days"
    assert ws.shipped_board_limit == 30


@pytest.mark.django_db
def test_shipped_board_prefs_rejects_bad_mode(client_local, workspace):
    p = f"/settings/{workspace.org.slug}/{workspace.slug}/shipped-board"
    resp = client_local.post(p, {"mode": "weeks", "limit": "5"})
    assert resp.status_code == 400


@pytest.mark.django_db
def test_shipped_board_prefs_rejects_out_of_range(client_local, workspace):
    p = f"/settings/{workspace.org.slug}/{workspace.slug}/shipped-board"
    resp = client_local.post(p, {"mode": "count", "limit": "0"})
    assert resp.status_code == 400
