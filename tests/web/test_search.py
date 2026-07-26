"""Cmd+K 서버 검색. absorb 케이스가 이 파일의 존재 이유다 — 정상 경로에서는
절대 재현되지 않고, 빠뜨리면 사용자에게 그냥 버그로 보인다."""

import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.refs import slice_ref, ticket_ref
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tickets import absorb_ticket, create_ticket, promote_ticket, resolve_ticket


@pytest.mark.django_db
def test_finds_a_slice_by_its_full_ref(client_local, org):
    s = create_slice(create_area(org, "OSS"), "Board redesign")
    body = client_local.get(f"/{org.slug}/search", {"q": slice_ref(s)}).content.decode()
    assert "Board redesign" in body


@pytest.mark.django_db
def test_finds_a_slice_by_a_bare_number(client_local, org):
    """Humans read the number off the screen without the prefix."""
    s = create_slice(create_area(org, "OSS"), "Board redesign")
    body = client_local.get(f"/{org.slug}/search", {"q": str(s.number)}).content.decode()
    assert "Board redesign" in body


@pytest.mark.django_db
def test_finds_by_title_substring(client_local, org):
    create_slice(create_area(org, "OSS"), "Board redesign")
    create_ticket(org, "Board is slow")
    body = client_local.get(f"/{org.slug}/search", {"q": "board"}).content.decode()
    assert "Board redesign" in body
    assert "Board is slow" in body


@pytest.mark.django_db
def test_does_not_leak_another_orgs_work(client_local, org):
    other = Org.objects.create(name="Other", slug="other-org")
    create_slice(create_area(other, "Secret"), "Confidential thing")
    body = client_local.get(f"/{org.slug}/search", {"q": "Confidential"}).content.decode()
    assert "Confidential thing" not in body


@pytest.mark.django_db
def test_an_absorbed_ticket_ref_says_where_it_went(client_local, org):
    """absorb_ticket does NOT hand its number over, so the ticket's ref resolves
    to a slice carrying a DIFFERENT ref. Landing there silently reads as a bug."""
    s = create_slice(create_area(org, "OSS"), "Auth overhaul")
    t = create_ticket(org, "Login is broken")
    absorb_ticket(t, into=s)

    body = client_local.get(f"/{org.slug}/search", {"q": ticket_ref(t)}).content.decode()
    assert "Auth overhaul" in body
    assert ticket_ref(t) in body          # what you asked for
    assert slice_ref(s) in body           # where you landed
    assert "absorbed" in body.lower()


@pytest.mark.django_db
def test_a_promoted_tickets_row_is_marked_resolved_but_its_slice_is_not(client_local, org):
    """promote_ticket copies the title onto the new Slice verbatim, and the
    Ticket row lives on afterward — so a title search returns both, with
    identical titles (and, since promote also hands over the number, identical
    refs). Nothing but a marker on the ticket row tells them apart."""
    area = create_area(org, "OSS")
    t = create_ticket(org, "Board redesign", area=area)
    promote_ticket(t)

    body = client_local.get(f"/{org.slug}/search", {"q": "Board redesign"}).content.decode()
    assert body.count('cmdk-result-title">Board redesign') == 2  # slice row AND the dead ticket row
    assert "ticket-status--promoted" in body
    assert body.count("ticket-status--") == 1  # only the ticket row is marked, not the slice


@pytest.mark.django_db
def test_a_dismissed_ticket_is_marked_resolved(client_local, org):
    t = create_ticket(org, "Login is broken")
    resolve_ticket(t, "dismissed")

    body = client_local.get(f"/{org.slug}/search", {"q": "Login is broken"}).content.decode()
    assert "Login is broken" in body
    assert "ticket-status--dismissed" in body


@pytest.mark.django_db
def test_an_open_ticket_has_no_resolved_marker(client_local, org):
    create_ticket(org, "Something new")

    body = client_local.get(f"/{org.slug}/search", {"q": "Something new"}).content.decode()
    assert "Something new" in body
    assert "ticket-status" not in body


@pytest.mark.django_db
def test_an_empty_query_returns_no_rows(client_local, org):
    create_slice(create_area(org, "OSS"), "Board redesign")
    body = client_local.get(f"/{org.slug}/search", {"q": ""}).content.decode()
    assert "Board redesign" not in body
