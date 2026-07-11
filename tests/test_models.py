import pytest
from django.db import IntegrityError

from tuckit.core.models import ApiToken, Org, OrgMember, User, Workspace


@pytest.mark.django_db
def test_workspace_defaults():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="MyProduct", slug="myproduct")
    assert ws.description == ""
    assert ws.created_at is not None


@pytest.mark.django_db
def test_workspace_slug_unique_within_org():
    # Workspace slug uniqueness is now scoped to org (unique_together(org, slug)),
    # not global. See tests/test_models_org.py for the cross-org case.
    org = Org.objects.create(name="Acme", slug="acme")
    Workspace.objects.create(org=org, name="A", slug="dup")
    with pytest.raises(IntegrityError):
        Workspace.objects.create(org=org, name="B", slug="dup")


@pytest.mark.django_db
def test_membership_is_unique_per_user_org():
    user = User.objects.create_user(username="bob", password="x")
    org = Org.objects.create(name="O", slug="o")
    OrgMember.objects.create(user=user, org=org, role="owner")
    with pytest.raises(IntegrityError):
        OrgMember.objects.create(user=user, org=org, role="member")


@pytest.mark.django_db
def test_api_token_hash_unique():
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="A", slug="a")
    ApiToken.objects.create(workspace=ws, name="t1", token_hash="abc")
    with pytest.raises(IntegrityError):
        ApiToken.objects.create(workspace=ws, name="t2", token_hash="abc")
