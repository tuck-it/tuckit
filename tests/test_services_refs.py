import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.exceptions import NotFound
from tuckit.core.services.refs import parse_ref, ref_for, slice_ref
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_slice_ref_uses_the_org_key():
    org = Org.objects.create(name="Tuckit Projects", slug="tuckit-projects")
    s = create_slice(org, area=create_area(org, "OSS"), title="MCP search")
    assert slice_ref(s) == f"TP-{s.number}"
    assert parse_ref(org, slice_ref(s)) == s.number


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
def test_ref_for_takes_a_slice_and_refuses_anything_else():
    """A Slice is the only thing that carries a number now — 0050 dropped the
    Ticket table, which was the second branch. The dispatch still raises rather
    than falling through, so the {% ref_of %} tag fails loudly instead of
    rendering 'None-None'."""
    org = Org.objects.create(name="Tuckit", slug="tuckit")
    s = create_slice(org, area=create_area(org, "OSS"), title="One")
    assert ref_for(s) == slice_ref(s)
    with pytest.raises(TypeError):
        ref_for(org)
