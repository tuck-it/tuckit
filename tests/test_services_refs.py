import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.refs import parse_ref, ref_for, slice_ref, ticket_ref
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tickets import create_ticket


@pytest.mark.django_db
def test_slice_ref_uses_the_org_key():
    org = Org.objects.create(name="Tuckit Projects", slug="tuckit-projects")
    s = create_slice(create_area(org, "OSS"), "MCP search")
    assert slice_ref(s) == f"TP-{s.number}"
    assert parse_ref(org, slice_ref(s)) == s.number


@pytest.mark.django_db
def test_ticket_ref_shares_the_same_shape():
    org = Org.objects.create(name="Tuckit", slug="tuckit")
    t = create_ticket(org, "Capture")
    assert ticket_ref(t) == f"TUC-{t.number}"


@pytest.mark.django_db
def test_parse_ref_is_case_insensitive():
    org = Org.objects.create(name="Tuckit", slug="tuckit")
    assert parse_ref(org, "tuc-9") == 9


@pytest.mark.django_db
def test_parse_ref_rejects_the_old_slug_form():
    """The pre-TUC format is deliberately dropped, not dual-parsed."""
    org = Org.objects.create(name="Tuckit Projects", slug="tuckit-projects")
    with pytest.raises(NotFound):
        parse_ref(org, "tuckit-projects-47")


@pytest.mark.django_db
def test_parse_ref_rejects_a_foreign_key_prefix():
    org = Org.objects.create(name="Tuckit", slug="tuckit")
    with pytest.raises(NotFound):
        parse_ref(org, "OTH-9")


@pytest.mark.django_db
def test_parse_ref_rejects_a_bare_number():
    """A bare number is resolved by the search view, not here — get_slice_flexible
    reads bare digits as primary keys and must keep doing so."""
    org = Org.objects.create(name="Tuckit", slug="tuckit")
    with pytest.raises(NotFound):
        parse_ref(org, "47")


@pytest.mark.django_db
def test_ref_for_dispatches_on_type():
    org = Org.objects.create(name="Tuckit", slug="tuckit")
    s = create_slice(create_area(org, "OSS"), "One")
    t = create_ticket(org, "Two")
    assert ref_for(s) == slice_ref(s)
    assert ref_for(t) == ticket_ref(t)
    with pytest.raises(TypeError):
        ref_for(org)
