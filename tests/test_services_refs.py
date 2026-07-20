import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.refs import slice_ref, parse_slice_ref
from tuckit.core.services.exceptions import NotFound


@pytest.mark.django_db
def test_slice_ref_and_parse_round_trip():
    org = Org.objects.create(name="Tuckit", slug="tuck-it")  # slug with a hyphen
    s = create_slice(create_area(org, "OSS"), "MCP search")
    ref = slice_ref(s)
    assert ref == f"tuck-it-{s.number}"
    assert parse_slice_ref(org, ref) == s.number


@pytest.mark.django_db
def test_parse_slice_ref_rejects_foreign_slug():
    org = Org.objects.create(name="Tuckit", slug="tuck-it")
    with pytest.raises(NotFound):
        parse_slice_ref(org, "other-9")
