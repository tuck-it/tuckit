import pytest

from tuckit.core.models import Area, Org, OrgMember, User, Workspace
from tuckit.core.services.accounts import register
from tuckit.core.services.exceptions import InvalidValue


@pytest.mark.django_db
def test_register_creates_user_and_org_no_workspace():
    user, org = register(
        email="a@b.com", org_name="Space", slug="space", password="pw123456"
    )
    assert user.email == "a@b.com"
    assert user.check_password("pw123456")
    assert org.slug == "space"
    assert OrgMember.objects.filter(user=user, org=org, role="owner").exists()
    assert Area.objects.filter(org=org, is_triage=True).count() == 1
    assert Area.objects.filter(org=org, is_triage=False).count() == 0
    assert Workspace.objects.filter(org=org).count() == 0


@pytest.mark.django_db
def test_register_does_not_set_username():
    user, _ = register(
        email="a@b.com", org_name="S", slug="s0", password="pw123456"
    )
    assert user.username is None


@pytest.mark.django_db
def test_register_duplicate_org_slug_raises():
    register(email="a@b.com", org_name="S", slug="dup", password="pw123456")
    with pytest.raises(InvalidValue):
        register(email="c@d.com", org_name="S2", slug="dup", password="pw123456")


@pytest.mark.django_db
def test_register_duplicate_email_raises():
    register(email="same@b.com", org_name="S", slug="s1", password="pw123456")
    with pytest.raises(InvalidValue):
        register(email="same@b.com", org_name="S2", slug="s2", password="pw123456")


@pytest.mark.django_db
def test_register_rejects_empty_password():
    with pytest.raises(InvalidValue):
        register(email="a@b.com", org_name="S", slug="s0", password="")


@pytest.mark.django_db
def test_register_rejects_weak_password():
    with pytest.raises(InvalidValue):
        register(email="a@b.com", org_name="S", slug="s0", password="abc")


@pytest.mark.django_db
def test_register_runs_signup_hook():
    from django.test import override_settings

    seen = {}

    def _hook(*, user, org):
        seen["ok"] = (user.email, org.slug)

    import tests.test_services_accounts as mod
    mod._hook = _hook
    with override_settings(TUCKIT_SIGNUP_HOOK="tests.test_services_accounts._hook"):
        register(email="h@b.com", org_name="H", slug="h0", password="pw123456")
    assert seen["ok"] == ("h@b.com", "h0")
