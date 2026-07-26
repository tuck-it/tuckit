import pytest
from django.db import IntegrityError

from tuckit.core.models import Org, OrgMember, Invitation, User


@pytest.mark.django_db
def test_org_and_membership_roundtrip():
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(email="a@b.com")
    m = OrgMember.objects.create(user=user, org=org, role="owner")
    assert m.role == "owner"
    assert list(org.members.all()) == [m]


@pytest.mark.django_db
def test_orgmember_unique_per_user_org():
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(email="a@b.com")
    OrgMember.objects.create(user=user, org=org, role="owner")
    with pytest.raises(IntegrityError):
        OrgMember.objects.create(user=user, org=org, role="member")


@pytest.mark.django_db
def test_invitation_defaults_pending():
    org = Org.objects.create(name="Acme", slug="acme")
    inv = Invitation.objects.create(org=org, email="x@y.com", role="member", token="tok123")
    assert inv.accepted_at is None


@pytest.mark.django_db
def test_org_has_workspace_fields_with_defaults():
    org = Org.objects.create(name="Acme", slug="acme")
    assert org.description == ""
    assert org.onboarding_dismissed is False
    assert org.onboarding_completed is False
    assert org.shipped_board_mode == "count"
    assert org.shipped_board_limit == 8
    assert org.updated_at is not None


@pytest.mark.django_db
def test_org_updated_at_advances_on_save():
    org = Org.objects.create(name="Acme", slug="acme")
    before = org.updated_at
    org.name = "Acme Inc"
    org.save(update_fields=["name", "updated_at"])
    org.refresh_from_db()
    assert org.updated_at > before


@pytest.mark.django_db
def test_org_member_starts_with_no_home_watermark():
    """home_seen_at is the only state behind "new since you last looked". It
    starts null so a first-ever visit badges nothing — a fresh account seeing
    "10 new" would be noise, not news."""
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user(email="a@example.com", password="x")
    m = OrgMember.objects.create(user=user, org=org, role="owner")

    assert m.home_seen_at is None


def test_org_key_is_derived_on_create(db):
    from tuckit.core.models import Org

    org = Org.objects.create(name="Tuckit Projects", slug="tuckit-projects")
    assert org.key == "TP"


def test_org_key_avoids_collision(db):
    from tuckit.core.models import Org

    Org.objects.create(name="One", slug="tuckit-projects")
    second = Org.objects.create(name="Two", slug="tuckit-plugins")
    assert second.key == "TP2"


def test_explicit_key_is_not_overwritten(db):
    from tuckit.core.models import Org

    org = Org.objects.create(name="Tuckit", slug="tuckit", key="ZZ")
    assert org.key == "ZZ"


def test_saving_an_existing_org_does_not_touch_its_key(db):
    from tuckit.core.models import Org

    org = Org.objects.create(name="Tuckit", slug="tuckit")
    org.name = "Renamed"
    org.save(update_fields=["name"])
    org.refresh_from_db()
    assert org.key == "TUC"


def test_org_creation_retries_past_a_racing_key_collision(db, monkeypatch):
    """unique_key() reads "taken" keys and the INSERT that follows are not
    atomic, so two concurrent signups can both compute the same free-looking
    key. Simulate the race (rather than real threads) by making unique_key
    hand back an already-taken key on the first attempt: the save should
    retry against fresh state instead of letting the IntegrityError become a
    500."""
    from tuckit.core.models import Org
    from tuckit.core.services import keys as keys_module

    Org.objects.create(name="Existing", slug="acme-corp", key="AC")

    handed_out = iter(["AC", "AC2"])  # "AC" collides, "AC2" is the real retry
    monkeypatch.setattr(keys_module, "unique_key", lambda base, taken: next(handed_out))

    org = Org.objects.create(name="Racer", slug="acme-inc")
    assert org.key == "AC2"


def test_org_creation_gives_up_after_bounded_retries(db, monkeypatch):
    """A persistently colliding key (a genuinely broken unique index, not a
    one-off race) must still fail loudly rather than loop forever."""
    from django.db import IntegrityError
    from tuckit.core.models import Org
    from tuckit.core.services import keys as keys_module

    Org.objects.create(name="Existing", slug="acme-corp", key="AC")
    monkeypatch.setattr(keys_module, "unique_key", lambda base, taken: "AC")

    with pytest.raises(IntegrityError):
        Org.objects.create(name="Racer", slug="acme-inc")
