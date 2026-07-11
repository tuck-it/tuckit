import pytest

from core.models import Area, Org, OrgMember, User, Workspace
from core.services.accounts import register
from core.services.exceptions import InvalidValue


@pytest.mark.django_db
def test_register_creates_user_org_workspace():
    user, org, ws = register(
        email="a@b.com", org_name="Space", slug="space", password="pw123456"
    )
    assert user.email == "a@b.com"
    assert user.username == "a@b.com"
    assert user.check_password("pw123456")
    assert org.slug == "space"
    assert ws.org == org
    assert OrgMember.objects.filter(user=user, org=org, role="owner").exists()
    assert Area.objects.filter(workspace=ws, is_inbox=True).count() == 1
    assert Area.objects.filter(workspace=ws, is_inbox=False, slug="default").exists()


@pytest.mark.django_db
def test_register_explicit_username():
    user, _, _ = register(
        email="a@b.com", org_name="S", slug="s", password="pw123456", username="alice"
    )
    assert user.username == "alice"


@pytest.mark.django_db
def test_register_duplicate_org_slug_raises():
    register(email="a@b.com", org_name="S", slug="dup", password="pw123456")
    with pytest.raises(InvalidValue):
        register(email="c@d.com", org_name="S2", slug="dup", password="pw123456", username="bob")


@pytest.mark.django_db
def test_register_duplicate_username_raises():
    register(email="a@b.com", org_name="S", slug="s1", password="pw123456", username="same")
    with pytest.raises(InvalidValue):
        register(email="c@d.com", org_name="S2", slug="s2", password="pw123456", username="same")


@pytest.mark.django_db
def test_register_rejects_empty_password():
    with pytest.raises(InvalidValue):
        register(email="a@b.com", org_name="S", slug="s", password="")


@pytest.mark.django_db
def test_register_rejects_weak_password():
    with pytest.raises(InvalidValue):
        register(email="a@b.com", org_name="S", slug="s", password="abc")


@pytest.mark.django_db
def test_register_runs_signup_hook():
    from django.test import override_settings

    seen = {}

    def _hook(*, user, org):
        seen["ok"] = (user.email, org.slug)

    import tests.test_services_accounts as mod
    mod._hook = _hook
    with override_settings(TUCKIT_SIGNUP_HOOK="tests.test_services_accounts._hook"):
        register(email="h@b.com", org_name="H", slug="h", password="pw123456")
    assert seen["ok"] == ("h@b.com", "h")
