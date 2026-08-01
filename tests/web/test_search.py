"""Cmd+K server search.

Slices only, and one row per piece of work. The Ticket branch this file used
to guard is gone with the table (0050): a ref now resolves to the slice holding
that number or to nothing at all.
"""

import pytest

from tuckit.core.models import Org, Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.refs import slice_ref
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_finds_a_slice_by_its_full_ref(client_local, org):
    s = create_slice(org, area=create_area(org, "OSS"), title="Board redesign")
    body = client_local.get(f"/{org.slug}/search", {"q": slice_ref(s)}).content.decode()
    assert "Board redesign" in body


@pytest.mark.django_db
def test_finds_a_slice_by_a_bare_number(client_local, org):
    """Humans read the number off the screen without the prefix."""
    s = create_slice(org, area=create_area(org, "OSS"), title="Board redesign")
    body = client_local.get(f"/{org.slug}/search", {"q": str(s.number)}).content.decode()
    assert "Board redesign" in body


@pytest.mark.django_db
def test_finds_by_title_substring(client_local, org):
    a = create_area(org, "OSS")
    create_slice(org, area=a, title="Board redesign")
    create_slice(org, area=a, title="Board is slow")
    body = client_local.get(f"/{org.slug}/search", {"q": "board"}).content.decode()
    assert "Board redesign" in body
    assert "Board is slow" in body


@pytest.mark.django_db
def test_does_not_leak_another_orgs_work(client_local, org):
    other = Org.objects.create(name="Other", slug="other-org")
    create_slice(other, area=create_area(other, "Secret"), title="Confidential thing")
    body = client_local.get(f"/{org.slug}/search", {"q": "Confidential"}).content.decode()
    assert "Confidential thing" not in body


@pytest.mark.django_db
def test_a_ref_nothing_holds_returns_no_exact_row(client_local, org):
    """The absorb case this file was built around is unreachable now. It needed
    a Ticket keeping its own number while its work moved under another slice's
    ref — 0050 dropped the table, so an unclaimed number resolves to nothing
    rather than to a second kind of object with no page to link to."""
    create_slice(org, area=create_area(org, "OSS"), title="Auth overhaul")

    body = client_local.get(f"/{org.slug}/search", {"q": f"{org.key}-9999"}).content.decode()
    assert "cmdk-result-title" not in body
    assert "No slice matches" in body


@pytest.mark.django_db
def test_a_folded_capture_returns_exactly_one_row(client_local, org):
    """0045 gives every folded capture a Slice with an IDENTICAL title and an
    IDENTICAL ref (promote handed the number over, and 0045 does the same).
    While search still queried Ticket alongside Slice, every one of the ~52
    production captures came back as TWO rows bearing the same ref in the
    product's primary lookup surface. There is one unit of work now, so there
    is one row."""
    area = create_area(org, "OSS")
    create_slice(org, area=area, title="Board redesign")

    body = client_local.get(f"/{org.slug}/search", {"q": "Board redesign"}).content.decode()
    assert body.count('cmdk-result-title">Board redesign') == 1
    # ...and the row that survived is the Slice, i.e. it links somewhere alive.
    s = Slice.objects.get(org=org, title="Board redesign")
    assert f'href="/{org.slug}/slices/{s.id}/"' in body
    assert body.count('class="cmdk-result-kind">slice') == 1


@pytest.mark.django_db
def test_the_empty_state_does_not_name_a_deleted_concept(client_local, org):
    body = client_local.get(f"/{org.slug}/search", {"q": "nothing here"}).content.decode()
    assert "No slice matches “nothing here”." in body
    assert "ticket" not in body.lower()


@pytest.mark.django_db
def test_an_empty_query_returns_no_rows(client_local, org):
    create_slice(org, area=create_area(org, "OSS"), title="Board redesign")
    body = client_local.get(f"/{org.slug}/search", {"q": ""}).content.decode()
    assert "Board redesign" not in body
