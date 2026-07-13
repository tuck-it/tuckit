import pytest
from django.test import override_settings

from tuckit.core.entitlements import Entitlements
from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.orgs import create_workspace


def _limit_1(org):
    return Entitlements(seat_limit=1)


@override_settings(TUCKIT_ENTITLEMENTS_HOOK="tests.web.test_seat_limit._limit_1")
@pytest.mark.django_db
def test_invite_over_limit_returns_402(client):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="o@a.com")
    owner.set_password("tuckit-seed-pw-9x2")
    owner.save()
    OrgMember.objects.create(user=owner, org=org, role="owner")  # 1 member == limit 1
    ws = create_workspace(org, "Board")
    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    resp = client.post(f"/settings/{org.slug}/invites", {"email": "new@x.com", "role": "member"})
    assert resp.status_code == 402
