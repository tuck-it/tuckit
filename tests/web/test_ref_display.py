"""ref가 다섯 화면에 실제로 렌더되는지. 엔드포인트 테스트로는 안 잡히는 종류라
응답 본문에서 문자열을 직접 확인한다."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tuckit.core.services.areas import create_area
from tuckit.core.services.refs import slice_ref, ticket_ref
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tickets import create_ticket


def _standalone_org_queries(ctx) -> int:
    """How many captured queries hit core_org as their own SELECT (i.e. the
    lazy `slice.org` / `ticket.org` fetch a missing select_related causes) —
    as opposed to a JOIN that pulls org columns into the same query as the
    slice/ticket row. Django always double-quotes identifiers on both sqlite
    and Postgres, so 'FROM "core_org"' only appears for the standalone form."""
    return sum(1 for q in ctx.captured_queries if 'FROM "core_org"' in q["sql"])


@pytest.mark.django_db
def test_board_card_shows_the_ref_even_when_the_meta_line_would_be_empty(client_local, org):
    """The area board renders cards with show_area=False, and a slice with no
    spec is stage 'needs_design' — exactly the pair that made the old
    `{% if show_area or slice.stage != "needs_design" %}` skip `.card-sub`
    entirely. If that condition is still there, this test fails.

    Rendered through the real view, not render_to_string: `{% detail_push_url %}`
    reads context["request"] and raises KeyError without one.
    """
    a = create_area(org, "OSS")
    s = create_slice(a, "Board redesign")
    assert s.spec == ""
    body = client_local.get(f"/{org.slug}/areas/{a.slug}/").content.decode()
    assert slice_ref(s) in body


@pytest.mark.django_db
def test_slice_detail_shows_a_copyable_ref(client_local, org):
    a = create_area(org, "OSS")
    s = create_slice(a, "Detail")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert slice_ref(s) in body
    assert "ref--copy" in body


@pytest.mark.django_db
def test_inbox_row_shows_the_ticket_ref(client_local, org):
    t = create_ticket(org, "Captured thing")
    body = client_local.get(f"/{org.slug}/inbox/").content.decode()
    assert ticket_ref(t) in body


@pytest.mark.django_db
def test_ticket_modal_shows_a_copyable_ref(client_local, org):
    t = create_ticket(org, "Captured thing")
    body = client_local.get(f"/{org.slug}/tickets/{t.id}/").content.decode()
    assert ticket_ref(t) in body
    assert "ref--copy" in body


@pytest.mark.django_db
def test_home_list_row_shows_the_ref(client_local, org):
    a = create_area(org, "OSS")
    s = create_slice(a, "In flight", status="building")
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert slice_ref(s) in body


@pytest.mark.django_db
def test_provenance_link_uses_the_new_format(client_local, org):
    """The slice detail's "promoted from" link built its ref by hand from the
    org SLUG. After the key switch that renders the wrong format — two ref
    shapes on one screen."""
    from tuckit.core.services.tickets import promote_ticket

    a = create_area(org, "OSS")
    t = create_ticket(org, "Original capture")
    s = promote_ticket(t, area=a)
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert ticket_ref(t) in body
    assert f"{org.slug}-{t.number}" not in body


@pytest.mark.django_db
def test_no_template_builds_a_ref_from_the_org_slug():
    """Guards the single-source rule itself: the format lives in refs.py, and a
    template that assembles one by hand silently drifts the day it changes."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "tuckit" / "web"
    files = list(root.rglob("*.html")) + list(root.rglob("*.py"))
    # A vacuous scan (wrong cwd, moved directory) would pass with an empty
    # offenders list just as happily as a real clean scan — assert we actually
    # looked at something.
    assert len(files) > 0
    offenders = [
        str(p)
        for p in files
        if "org_slug_ref" in p.read_text()
        or "current_org.slug }}-{{" in p.read_text()
    ]
    assert offenders == []


# --- Important 1: no N+1 on Org across list surfaces -----------------------
#
# refs.py reads slice_.org.key / ticket.org.key on every row. None of these
# surfaces select_related("org") on purpose in this test — an area, several
# slices and a ticket are enough rows that a per-row org fetch would show up
# as query count scaling with row count. Each surface asserts a fixed ceiling
# a couple above its own measured baseline, so it survives an unrelated query
# being added elsewhere on the page without going stale, but still fails hard
# if org drops out of a select_related and the N+1 (one query per row, so +6
# here) comes back.


@pytest.mark.django_db
def test_home_bands_do_not_n_plus_one_on_org(client_local, org):
    a = create_area(org, "OSS")
    for i in range(6):
        create_slice(a, f"Building {i}", status="building")
    with CaptureQueriesContext(connection) as ctx:
        client_local.get(f"/{org.slug}/")
    assert _standalone_org_queries(ctx) <= 4


@pytest.mark.django_db
def test_board_does_not_n_plus_one_on_org(client_local, org):
    a = create_area(org, "OSS")
    for i in range(6):
        create_slice(a, f"Slice {i}")
    with CaptureQueriesContext(connection) as ctx:
        client_local.get(f"/{org.slug}/roadmap/")
    assert _standalone_org_queries(ctx) <= 4


@pytest.mark.django_db
def test_inbox_does_not_n_plus_one_on_org(client_local, org):
    for i in range(6):
        create_ticket(org, f"Ticket {i}")
    with CaptureQueriesContext(connection) as ctx:
        client_local.get(f"/{org.slug}/inbox/")
    assert _standalone_org_queries(ctx) <= 4


@pytest.mark.django_db
def test_area_board_does_not_n_plus_one_on_org(client_local, org):
    a = create_area(org, "OSS")
    for i in range(6):
        create_slice(a, f"Slice {i}")
    with CaptureQueriesContext(connection) as ctx:
        client_local.get(f"/{org.slug}/areas/{a.slug}/")
    assert _standalone_org_queries(ctx) <= 5
