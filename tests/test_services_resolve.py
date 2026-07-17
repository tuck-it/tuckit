import pytest

from tuckit.core.models import Org, Workspace
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.plans import create_plan
from tuckit.core.services.resolve import get_area, get_bite, get_slice
from tuckit.core.services.slices import create_slice


@pytest.fixture
def data(db):
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="A", slug="a")
    # A different org, not just a different workspace: resolve.py's
    # get_area/get_slice/get_bite are now org-scoped (Org is the tenant
    # boundary), so "rejects other tenant" must use a genuinely different org.
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other = Workspace.objects.create(org=other_org, name="B", slug="b")
    area = create_area(ws.org, "Backend")
    slice_ = create_slice(area, "Auth")
    plan = create_plan(slice_, title="Plan")
    bite = create_bite(plan, "JWT")
    return ws, other, area, slice_, bite


@pytest.mark.django_db
def test_get_area_returns_own(data):
    ws, _other, area, _s, _b = data
    assert get_area(ws.org, area.id) == area


@pytest.mark.django_db
def test_get_area_rejects_other_workspace(data):
    _ws, other, area, _s, _b = data
    with pytest.raises(NotFound):
        get_area(other.org, area.id)


@pytest.mark.django_db
def test_get_area_rejects_missing(data):
    ws, _other, _area, _s, _b = data
    with pytest.raises(NotFound):
        get_area(ws.org, 999999)


@pytest.mark.django_db
def test_get_slice_scoped(data):
    ws, other, _area, slice_, _b = data
    assert get_slice(ws.org, slice_.id) == slice_
    with pytest.raises(NotFound):
        get_slice(other.org, slice_.id)


@pytest.mark.django_db
def test_get_bite_scoped(data):
    ws, other, _area, _s, bite = data
    assert get_bite(ws.org, bite.id) == bite
    with pytest.raises(NotFound):
        get_bite(other.org, bite.id)
