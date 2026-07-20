import pytest
from django.contrib.auth import get_user_model

from tuckit.core.models import Org, OrgMember
from tuckit.core.services.exceptions import InvalidValue, NotFound
from tuckit.core.services.members import resolve_member


@pytest.fixture
def org_user(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = get_user_model().objects.create_user(email="a@b.co", password="pw123456")
    member = OrgMember.objects.create(user=user, org=org, role="member")
    return org, user, member


@pytest.mark.django_db
def test_resolve_member_empty_clears(org_user):
    org, _u, _m = org_user
    assert resolve_member(org, "") is None


@pytest.mark.django_db
def test_resolve_member_by_email(org_user):
    org, _u, member = org_user
    assert resolve_member(org, "a@b.co") == member


@pytest.mark.django_db
def test_resolve_member_me_uses_caller(org_user):
    org, user, member = org_user
    assert resolve_member(org, "me", caller_user=user) == member


@pytest.mark.django_db
def test_resolve_member_me_without_user_raises(org_user):
    org, _u, _m = org_user
    with pytest.raises(InvalidValue):
        resolve_member(org, "me", caller_user=None)


@pytest.mark.django_db
def test_resolve_member_unknown_email_raises(org_user):
    org, _u, _m = org_user
    with pytest.raises(NotFound):
        resolve_member(org, "nobody@x.co")
