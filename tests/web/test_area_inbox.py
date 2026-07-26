"""Area 페이지의 Inbox 스트립. area가 정해진 open 티켓은 Inbox와 그 Area 양쪽에
보인다 — area는 분류일 뿐이므로 티켓은 여전히 미트리아지 상태다.

스트립은 보드 칼럼이 아니라 보드 '위'의 별도 줄이다. Ticket을 Planned 옆에 두면
'아직 약속 안 함'과 '하기로 함'의 구분이 형태만 바꿔 무너진다.
"""
import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.state import area_board_view
from tuckit.core.services.tickets import create_ticket, resolve_ticket


P = lambda org: f"/{org.slug}"


@pytest.mark.django_db
def test_area_board_view_reports_that_areas_open_tickets(org):
    area = create_area(org, "Backend")
    other = create_area(org, "Frontend")
    mine = create_ticket(org, "retry webhooks", area=area)
    create_ticket(org, "someone else's", area=other)
    create_ticket(org, "unfiled")

    tickets = area_board_view(area)["tickets"]

    assert [t.id for t in tickets] == [mine.id]


@pytest.mark.django_db
def test_triaged_tickets_leave_the_strip(org):
    """스트립은 open만 담는다 — dismissed된 티켓이 남으면 '분류 대기'라는
    말이 거짓이 된다."""
    area = create_area(org, "Backend")
    t = create_ticket(org, "nope", area=area)
    resolve_ticket(t, "dismissed", actor="human")

    assert area_board_view(area)["tickets"] == []


@pytest.mark.django_db
def test_area_page_shows_the_strip_and_opens_the_ticket_modal(client_local, org):
    area = create_area(org, "Backend")
    create_ticket(org, "retry webhooks", area=area)

    body = client_local.get(f"{P(org)}/areas/{area.slug}/").content.decode()

    assert "retry webhooks" in body
    assert "untriaged" in body
    # 행은 기존 티켓 상세 모달을 연다 — 트리아지 컨트롤을 세 번째 장소에
    # 복제하지 않는다.
    assert 'hx-target="#detail-modal"' in body


@pytest.mark.django_db
def test_the_strip_is_absent_when_there_is_nothing_to_triage(client_local, org):
    """0건이면 줄 자체를 렌더하지 않는다. 빈 상태 문구는 노이즈다 — 보드가
    이미 그 area의 주된 내용이다."""
    area = create_area(org, "Backend")
    create_slice(area, "a slice")

    body = client_local.get(f"{P(org)}/areas/{area.slug}/").content.decode()

    assert "untriaged" not in body


@pytest.mark.django_db
def test_the_strip_is_absent_from_the_status_filter_view(client_local, org):
    """?status= 플랫 리스트는 보드를 대체하는 아카이브 화면이다. 스트립은
    보드 화면에만 붙으므로 여기서는 나오지 않는다."""
    area = create_area(org, "Backend")
    create_ticket(org, "retry webhooks", area=area)

    body = client_local.get(f"{P(org)}/areas/{area.slug}/?status=shipped").content.decode()

    assert "untriaged" not in body


@pytest.mark.django_db
def test_the_strip_renders_collapsed(client_local, org):
    """서버는 <details>를 닫힌 채 렌더한다.

    열림 여부는 클라이언트 선호(localStorage)이고, idiomorph가 2초마다
    #main-content를 서버 렌더값으로 morph한다. 여기에 open을 되살리면
    heat.js의 속성 보호막과 싸우게 되고, 사용자 선택이 매 폴링마다 덮인다.
    복원 스크립트는 반드시 이 스트립과 함께 렌더되어야 한다 — 빠지면 기능이
    조용히 되돌아가도 스위트는 계속 초록색이다.
    """
    area = create_area(org, "Backend")
    create_ticket(org, "retry webhooks", area=area)

    body = client_local.get(f"{P(org)}/areas/{area.slug}/").content.decode()

    assert '<details class="area-inbox">' in body
    assert "area-inbox-open" in body  # the restore script ships with the strip
