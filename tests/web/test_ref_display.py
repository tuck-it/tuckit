"""ref가 다섯 화면에 실제로 렌더되는지. 엔드포인트 테스트로는 안 잡히는 종류라
응답 본문에서 문자열을 직접 확인한다."""

import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.refs import slice_ref, ticket_ref
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tickets import create_ticket


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

    root = pathlib.Path("tuckit/web")
    offenders = [
        str(p)
        for p in list(root.rglob("*.html")) + list(root.rglob("*.py"))
        if "org_slug_ref" in p.read_text()
        or "current_org.slug }}-{{" in p.read_text()
    ]
    assert offenders == []
