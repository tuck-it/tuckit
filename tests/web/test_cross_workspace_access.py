import pytest

from core.models import Org, OrgMember, Slice, User
from core.services.orgs import create_workspace


@pytest.mark.django_db
def test_cannot_open_slice_from_another_org(client):
    org_a = Org.objects.create(name="A", slug="a")
    user_a = User.objects.create(username="a@a.com", email="a@a.com")
    OrgMember.objects.create(user=user_a, org=org_a, role="owner")
    ws_a = create_workspace(org_a, "A-Board")

    org_b = Org.objects.create(name="B", slug="b")
    ws_b = create_workspace(org_b, "B-Board")
    area_b = ws_b.areas.get(is_inbox=True)
    foreign = Slice.objects.create(area=area_b, title="secret", rank="m")

    client.force_login(user_a)
    session = client.session
    session["active_workspace_id"] = ws_a.id
    session.save()

    resp = client.get(f"/slices/{foreign.id}/")
    assert resp.status_code == 404
