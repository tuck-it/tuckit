"""Cmd+K 서버 검색. absorb 케이스가 이 파일의 존재 이유다 — 정상 경로에서는
절대 재현되지 않고, 빠뜨리면 사용자에게 그냥 버그로 보인다."""

import pytest

from tuckit.core.models import Org, Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.refs import slice_ref, ticket_ref
from tuckit.core.services.slices import create_slice
from tests.legacy_tickets import legacy_absorbed, legacy_promoted, legacy_resolved, legacy_ticket


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
def test_an_absorbed_ticket_ref_says_where_it_went(client_local, org):
    """An absorb did NOT hand the ticket's number over, so the ticket's ref
    resolves to a slice carrying a DIFFERENT ref. Landing there silently reads
    as a bug."""
    s = create_slice(org, area=create_area(org, "OSS"), title="Auth overhaul")
    t = legacy_ticket(org, "Login is broken")
    legacy_absorbed(t, s)

    body = client_local.get(f"/{org.slug}/search", {"q": ticket_ref(t)}).content.decode()
    assert "Auth overhaul" in body
    assert ticket_ref(t) in body          # what you asked for
    assert slice_ref(s) in body           # where you landed
    assert "absorbed" in body.lower()


@pytest.mark.django_db
def test_a_folded_capture_returns_exactly_one_row(client_local, org):
    """0045 gives every folded capture a Slice with an IDENTICAL title and an
    IDENTICAL ref (promote handed the number over, and 0045 does the same).
    While search still queried Ticket alongside Slice, every one of the ~52
    production captures came back as TWO rows bearing the same ref in the
    product's primary lookup surface. There is one unit of work now, so there
    is one row."""
    area = create_area(org, "OSS")
    legacy_promoted(org, "Board redesign", area=area)

    body = client_local.get(f"/{org.slug}/search", {"q": "Board redesign"}).content.decode()
    assert body.count('cmdk-result-title">Board redesign') == 1
    # ...and the row that survived is the Slice, i.e. it links somewhere alive.
    s = Slice.objects.get(org=org, title="Board redesign")
    assert f'href="/{org.slug}/slices/{s.id}/"' in body
    assert body.count('class="cmdk-result-kind">slice') == 1


@pytest.mark.django_db
def test_a_ticket_that_never_became_a_slice_is_not_offered(client_local, org):
    """A Ticket 0045 could not fold has no page of its own any more — web:ticket
    only forwards to a Slice. Emitting a row for it would hand the palette an
    href that dead-ends, so it is simply not a result."""
    legacy_resolved(legacy_ticket(org, "Login is broken"), "dismissed")

    body = client_local.get(f"/{org.slug}/search", {"q": "Login is broken"}).content.decode()
    # (the empty state echoes the query back, so assert on rows, not the title)
    assert "cmdk-result-title" not in body
    assert "No slice matches" in body


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
