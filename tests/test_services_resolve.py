import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.plans import create_plan
from tuckit.core.services.resolve import get_area, get_bite, get_slice
from tuckit.core.services.slices import create_slice


@pytest.fixture
def data(db):
    org = Org.objects.create(name="Acme", slug="acme")
    # get_area/get_slice/get_bite are org-scoped (Org is the tenant boundary),
    # so "rejects other tenant" must use a genuinely different org.
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    area = create_area(org, "Backend")
    slice_ = create_slice(area, "Auth")
    plan = create_plan(slice_, title="Plan")
    bite = create_bite(plan, "JWT")
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
    from tuckit.core.services.resolve import get_slice_by_ref, get_slice_flexible

    org = Org.objects.create(name="Acme", slug="acme")
    s = create_slice(create_area(org, "B"), "Auth")
    assert get_slice_by_ref(org, f"acme-{s.number}").id == s.id
    assert get_slice_flexible(org, f"acme-{s.number}").id == s.id
    assert get_slice_flexible(org, s.id).id == s.id


@pytest.mark.django_db
def test_absorbed_ticket_ref_resolves_to_the_owning_slice():
    """A ref names a piece of work and resolves to its current form. After an
    absorb the work lives on the slice, so the absorbed ticket's ref must lead
    there too — otherwise the invariant holds for promotion but not for merges."""
    from tuckit.core.models import Org
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.refs import ticket_ref
    from tuckit.core.services.resolve import resolve_ref
    from tuckit.core.services.tickets import absorb_ticket, create_ticket, promote_ticket

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    s = promote_ticket(create_ticket(org, "Origin", area=area))
    extra = create_ticket(org, "Extra", area=area)
    extra_ref = ticket_ref(extra)
    absorb_ticket(extra, s)

    assert resolve_ref(org, extra_ref) == s


@pytest.mark.django_db
def test_released_ticket_ref_goes_back_to_the_ticket():
    from tuckit.core.models import Org
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.refs import ticket_ref
    from tuckit.core.services.resolve import resolve_ref
    from tuckit.core.services.tickets import (
        absorb_ticket, create_ticket, promote_ticket, release_ticket,
    )

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    s = promote_ticket(create_ticket(org, "Origin", area=area))
    extra = create_ticket(org, "Extra", area=area)
    absorb_ticket(extra, s)
    release_ticket(extra)
    extra.refresh_from_db()

    assert resolve_ref(org, ticket_ref(extra)) == extra
