import pytest
from pathlib import Path

from tuckit.core.models import Org, Workspace
from tuckit.core.services.tokens import generate_token, hash_token, list_tokens, resolve_workspace, revoke_token


@pytest.fixture
def workspace(db):
    org = Org.objects.create(name="Acme", slug="acme")
    return Workspace.objects.create(org=org, name="P", slug="p")


@pytest.mark.django_db
def test_generate_token_stores_only_hash(workspace):
    token, raw = generate_token(workspace, "cli")
    assert raw and len(raw) > 20
    assert token.token_hash == hash_token(raw)
    assert token.token_hash != raw


@pytest.mark.django_db
def test_resolve_workspace_returns_owner_and_stamps_use(workspace):
    _, raw = generate_token(workspace, "cli")
    resolved = resolve_workspace(raw)
    assert resolved == workspace
    from tuckit.core.models import ApiToken

    assert ApiToken.objects.get(workspace=workspace).last_used_at is not None


@pytest.mark.django_db
def test_resolve_workspace_returns_none_for_bad_token(workspace):
    generate_token(workspace, "cli")
    assert resolve_workspace("not-a-real-token") is None


@pytest.mark.django_db
def test_list_and_revoke_tokens():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="W", slug="w")
    t, _ = generate_token(ws, "a")
    assert list(list_tokens(ws)) == [t]
    revoke_token(ws, t.id)
    assert list(list_tokens(ws)) == []


@pytest.mark.django_db
def test_revoke_token_is_workspace_scoped(workspace):
    org = Org.objects.create(name="Other Org", slug="other-org")
    other = Workspace.objects.create(org=org, name="Other", slug="other")
    token, _ = generate_token(other, "cli")
    revoke_token(workspace, token.id)
    assert list(list_tokens(other)) == [token]


def test_new_neutral_and_warn_tokens_present():
    css = (Path(__file__).resolve().parent.parent / "tuckit/web/static/web/tokens.css").read_text()
    # both tokens defined for light and dark
    assert css.count("--warn:") >= 2
    assert css.count("--active:") >= 2
