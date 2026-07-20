import pytest
from django.db import IntegrityError

from tuckit.core.models import SocialAccount, User


@pytest.mark.django_db
def test_social_account_links_to_user():
    u = User.objects.create_user(email="a@b.com", password="pw123456")
    sa = SocialAccount.objects.create(user=u, provider="google", uid="sub-123")
    assert sa.user == u
    assert list(u.social_accounts.all()) == [sa]


@pytest.mark.django_db
def test_provider_uid_is_unique():
    u = User.objects.create_user(email="a@b.com", password="pw123456")
    SocialAccount.objects.create(user=u, provider="google", uid="sub-123")
    with pytest.raises(IntegrityError):
        SocialAccount.objects.create(user=u, provider="google", uid="sub-123")


@pytest.mark.django_db
def test_same_uid_different_provider_is_allowed():
    u = User.objects.create_user(email="a@b.com", password="pw123456")
    SocialAccount.objects.create(user=u, provider="google", uid="dup")
    SocialAccount.objects.create(user=u, provider="github", uid="dup")  # no raise
    assert u.social_accounts.count() == 2
