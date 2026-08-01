import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.resolve import get_area, get_bite, get_slice
from tuckit.core.services.slices import create_slice


@pytest.fixture
def data(db):
    org = Org.objects.create(name="Acme", slug="acme")
    # get_area/get_slice/get_bite are org-scoped (Org is the tenant boundary),
    # so "rejects other tenant" must use a genuinely different org.
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    area = create_area(org, "Backend")
    slice_ = create_slice(area.org, area=area, title="Auth")
    bite = create_bite(slice_, "JWT")
    return org, other_org, area, slice_, bite


@pytest.mark.django_db
def test_get_area_returns_own(data):
    org, _other_org, area, _s, _b = data
    assert get_area(org, area.id) == area


@pytest.mark.django_db
def test_get_area_rejects_other_workspace(data):
    _org, other_org, area, _s, _b = data
    with pytest.raises(NotFound):
        get_area(other_org, area.id)


@pytest.mark.django_db
def test_get_area_rejects_missing(data):
    org, _other_org, _area, _s, _b = data
    with pytest.raises(NotFound):
        get_area(org, 999999)


@pytest.mark.django_db
def test_get_slice_scoped(data):
    org, other_org, _area, slice_, _b = data
    assert get_slice(org, slice_.id) == slice_
    with pytest.raises(NotFound):
        get_slice(other_org, slice_.id)


@pytest.mark.django_db
def test_get_bite_scoped(data):
    org, other_org, _area, _s, bite = data
    assert get_bite(org, bite.id) == bite
    with pytest.raises(NotFound):
        get_bite(other_org, bite.id)


@pytest.mark.django_db
def test_get_slice_by_ref_and_flexible():
    from tuckit.core.services.refs import slice_ref
    from tuckit.core.services.resolve import get_slice_by_ref, get_slice_flexible

    org = Org.objects.create(name="Acme", slug="acme")
    s = create_slice(org, area=create_area(org, "B"), title="Auth")
    assert get_slice_by_ref(org, slice_ref(s)).id == s.id
    assert get_slice_flexible(org, slice_ref(s)).id == s.id
    assert get_slice_flexible(org, s.id).id == s.id


@pytest.mark.django_db
def test_a_ref_no_slice_holds_is_not_found():
    """resolve_ref() is gone with the Ticket table: a ref that no slice claims
    used to fall through to a Ticket, and that fallback was the only reason a
    second lookup existed alongside get_slice_by_ref(). Now there is one
    lookup and one answer."""
    from tuckit.core.services.exceptions import NotFound
    from tuckit.core.services.resolve import get_slice_by_ref

    org = Org.objects.create(name="Acme", slug="acme")
    with pytest.raises(NotFound):
        get_slice_by_ref(org, f"{org.key}-9999")


def test_no_ticket_era_lookup_survives_in_resolve():
    """A wiring guard, not a behaviour test. Each of these read the Ticket
    table; leaving one importable would leave a caller able to reach for a
    lookup that can only ever raise now that the table is gone."""
    from tuckit.core.services import resolve

    for name in ("resolve_ref", "get_ticket", "get_ticket_by_ref", "slice_for_ticket"):
        assert not hasattr(resolve, name), name
