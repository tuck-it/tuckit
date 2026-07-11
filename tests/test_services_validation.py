import pytest

from core.models import Org, Workspace
from core.services.areas import create_area
from core.services.bites import create_bite, set_bite_status
from core.services.exceptions import InvalidValue
from core.services.slices import create_slice, set_slice_status, update_slice


@pytest.fixture
def area(db):
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="A", slug="a")
    return create_area(ws, "Backend")


@pytest.mark.django_db
def test_create_slice_rejects_bad_status(area):
    with pytest.raises(InvalidValue):
        create_slice(area, "X", status="blocked")


@pytest.mark.django_db
def test_set_slice_status_rejects_bad_status(area):
    s = create_slice(area, "X")
    with pytest.raises(InvalidValue):
        set_slice_status(s, "nope")


@pytest.mark.django_db
def test_update_slice_rejects_bad_status(area):
    s = create_slice(area, "X")
    with pytest.raises(InvalidValue):
        update_slice(s, status="nope")


@pytest.mark.django_db
def test_valid_status_still_works(area):
    s = create_slice(area, "X", status="planned")
    set_slice_status(s, "shipped")
    s.refresh_from_db()
    assert s.status == "shipped"


@pytest.mark.django_db
def test_bite_status_validation(area):
    s = create_slice(area, "X")
    with pytest.raises(InvalidValue):
        create_bite(s, "B", status="wip")
    b = create_bite(s, "B2")
    with pytest.raises(InvalidValue):
        set_bite_status(b, "wip")
