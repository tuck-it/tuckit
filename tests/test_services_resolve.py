import pytest

from tuckit.core.models import Org, Workspace
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.resolve import get_area, get_bite, get_slice
from tuckit.core.services.slices import create_slice


@pytest.fixture
def data(db):
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="A", slug="a")
    other = Workspace.objects.create(org=org, name="B", slug="b")
    area = create_area(ws, "Backend")
    slice_ = create_slice(area, "Auth")
    bite = create_bite(slice_, "JWT")
    return ws, other, area, slice_, bite


@pytest.mark.django_db
def test_get_area_returns_own(data):
    ws, _other, area, _s, _b = data
    assert get_area(ws, area.id) == area


@pytest.mark.django_db
def test_get_area_rejects_other_workspace(data):
    _ws, other, area, _s, _b = data
    with pytest.raises(NotFound):
        get_area(other, area.id)


@pytest.mark.django_db
def test_get_area_rejects_missing(data):
    ws, _other, _area, _s, _b = data
    with pytest.raises(NotFound):
        get_area(ws, 999999)


@pytest.mark.django_db
def test_get_slice_scoped(data):
    ws, other, _area, slice_, _b = data
    assert get_slice(ws, slice_.id) == slice_
    with pytest.raises(NotFound):
        get_slice(other, slice_.id)


@pytest.mark.django_db
def test_get_bite_scoped(data):
    ws, other, _area, _s, bite = data
    assert get_bite(ws, bite.id) == bite
    with pytest.raises(NotFound):
        get_bite(other, bite.id)
