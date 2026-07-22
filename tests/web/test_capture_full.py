"""캡처는 언제나 Ticket을 만든다. Area는 분기 장치가 아니라 선택적 분류이므로,
area를 골라도 티켓은 open인 채로 Inbox에 남는다. Slice는 Area 페이지의
"+ New slice" 또는 티켓 promote로만 생긴다.

이전 버전은 정반대였다 — area를 채우면 Slice가 만들어지고 그 슬라이스로
리다이렉트됐다. 그래서 "area는 아는데 아직 할지는 모르겠는" 아이디어를
넣을 방법이 아예 없었다."""
import pytest

from tuckit.core.models import Org, Slice, Ticket
from tuckit.core.services.areas import create_area


P = lambda org: f"/{org.slug}"


@pytest.mark.django_db
def test_capture_title_only_stays_quick(client_local, org):
    """Title만: unfiled Ticket, 200 토스트 번들, 리다이렉트 없음."""
    resp = client_local.post(f"{P(org)}/capture", {"title": "quick one"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert "HX-Redirect" not in resp
    t = Ticket.objects.get(title="quick one")
    assert t.area is None and t.status == "open"


@pytest.mark.django_db
def test_capture_with_an_area_still_makes_an_open_ticket(client_local, org):
    """핵심 반전. area를 고르는 것은 분류이지 약속이 아니다 — 티켓은 open으로
    남고 Slice는 생기지 않는다."""
    backend = create_area(org, "Backend")
    resp = client_local.post(
        f"{P(org)}/capture", {"title": "in area", "area_id": backend.id}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 200
    assert "HX-Redirect" not in resp
    t = Ticket.objects.get(title="in area")
    assert t.area_id == backend.id and t.status == "open"
    assert not Slice.objects.filter(title="in area").exists()


@pytest.mark.django_db
def test_capture_note_without_area_makes_a_ticket_with_a_body(client_local, org):
    """note는 ticket.body로 간다. 이게 없으면 body는 MCP로만 쓸 수 있고,
    Inbox를 트리아지하는 사람은 제목 하나로 결정해야 한다."""
    resp = client_local.post(
        f"{P(org)}/capture",
        {"title": "OAuth screen is ugly", "spec": "buttons misaligned on mobile"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    t = Ticket.objects.get(org=org, title="OAuth screen is ugly")
    assert t.body == "buttons misaligned on mobile"
    assert t.area is None and t.status == "open"
    assert not Slice.objects.filter(title="OAuth screen is ugly").exists()


@pytest.mark.django_db
def test_capture_note_with_an_area_keeps_both(client_local, org):
    area = create_area(org, "Backend")
    resp = client_local.post(
        f"{P(org)}/capture",
        {"title": "Retry webhooks", "spec": "exponential backoff", "area_id": area.id},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    t = Ticket.objects.get(title="Retry webhooks")
    assert t.body == "exponential backoff" and t.area_id == area.id
    assert not Slice.objects.filter(title="Retry webhooks").exists()


@pytest.mark.django_db
def test_capture_requires_title(client_local, org):
    resp = client_local.post(
        f"{P(org)}/capture", {"title": "   ", "spec": "orphan"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 400
    assert not Ticket.objects.filter(body="orphan").exists()


@pytest.mark.django_db
def test_capture_ignores_a_stale_status_or_tags_post(client_local, org):
    """status/tags는 폼에서 사라졌다. 옛 클라이언트나 손으로 만든 POST가 보내도
    400이 아니라 조용히 무시한다 — Ticket에 담을 곳이 없을 뿐, 캡처 자체를
    거부할 이유는 없다. (예전에는 400이었고, 그 가드는 필드가 존재했기 때문에
    필요했다.)"""
    area = create_area(org, "Backend")
    resp = client_local.post(
        f"{P(org)}/capture",
        {"title": "stale client", "area_id": area.id, "status": "building", "tags": ["x"]},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    t = Ticket.objects.get(title="stale client")
    assert t.status == "open" and t.area_id == area.id
    assert not Slice.objects.filter(title="stale client").exists()


@pytest.mark.django_db
def test_capture_foreign_area_404s(client_local, org):
    """다른 org의 area id를 넣으면 404. get_area가 org 스코프를 건다."""
    other = Org.objects.create(name="Other Org", slug="other-org")
    foreign = create_area(other, "Theirs")
    resp = client_local.post(
        f"{P(org)}/capture", {"title": "cross tenant", "area_id": foreign.id},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 404
    assert not Ticket.objects.filter(title="cross tenant").exists()


@pytest.mark.django_db
def test_capture_modal_offers_no_slice_only_fields(client_local, org):
    """Ticket에 없는 필드는 폼에도 없다. status/tags를 내주는 것이 애초에
    'area를 고르면 planned가 된다'를 만든 원인이었다."""
    create_area(org, "Backend")
    body = client_local.get(f"{P(org)}/inbox/").content.decode()
    assert 'name="title"' in body
    assert 'name="spec"' in body
    assert 'name="area_id"' in body
    assert 'name="status"' not in body
    assert 'name="tags"' not in body
    # Inbox는 Area와 같은 층위가 아니다 — 드롭다운의 선택지가 될 수 없다.
    assert ">Unfiled<" in body
    assert ">Inbox<" not in body
    assert "Backend" in body
