"""캡처는 이제 언제나 Slice를 만든다 — Slice가 유일한 작업 단위이므로 더는
분기할 Ticket이 없다. Area는 분류가 아니라 목적지 그 자체다: 고르면 그
자리에 바로 파일링되고, 비우면 area 없는 Slice로 Inbox에 남는다. 둘 다 진짜
목적지이지, 어느 한쪽이 "아직 결정 안 된" 임시 상태인 게 아니다.

Task 8 이전에는 정반대였다 — 캡처는 언제나 Ticket을 만들었고, area를 골라도
그 Ticket은 여전히 open인 채로 Inbox에 남았다(파일링과 커밋은 다른 축이라는
전제). 그 전제가 이제 이 화면에서는 사라졌다: 유닛이 하나(Slice)뿐이므로
파일링이 곧 커밋이다."""
import pytest

from tuckit.core.models import Org, Slice
from tuckit.core.services.areas import create_area


P = lambda org: f"/{org.slug}"


@pytest.mark.django_db
def test_capture_without_area_creates_an_inbox_slice(client_local, org):
    r = client_local.post(f"/{org.slug}/capture", {"title": "떠오른 것", "spec": "본문"})
    assert r.status_code == 200
    s = Slice.objects.get(title="떠오른 것")
    assert s.area_id is None and s.spec == "본문"


@pytest.mark.django_db
def test_capture_with_area_files_it_immediately(client_local, org, area):
    client_local.post(
        f"/{org.slug}/capture", {"title": "정리됨", "spec": "", "area_id": area.id},
    )
    assert Slice.objects.get(title="정리됨").area_id == area.id


@pytest.mark.django_db
def test_capture_modal_says_slice_not_ticket(client_local, org):
    body = client_local.get(f"/{org.slug}/").content.decode()
    assert "New slice" in body
    assert "New ticket" not in body


@pytest.mark.django_db
def test_capture_title_only_stays_quick(client_local, org):
    """Title만: area 없는 open Slice, 200 토스트 번들, 리다이렉트 없음."""
    resp = client_local.post(f"{P(org)}/capture", {"title": "quick one"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert "HX-Redirect" not in resp
    s = Slice.objects.get(title="quick one")
    assert s.area is None and s.status == "open"


@pytest.mark.django_db
def test_capture_note_without_area_makes_a_slice_with_a_spec(client_local, org):
    """note는 이제 slice.spec으로 간다(예전엔 ticket.body)."""
    resp = client_local.post(
        f"{P(org)}/capture",
        {"title": "OAuth screen is ugly", "spec": "buttons misaligned on mobile"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    s = Slice.objects.get(org=org, title="OAuth screen is ugly")
    assert s.spec == "buttons misaligned on mobile"
    assert s.area is None and s.status == "open"


@pytest.mark.django_db
def test_capture_note_with_an_area_keeps_both(client_local, org):
    backend = create_area(org, "Backend")
    resp = client_local.post(
        f"{P(org)}/capture",
        {"title": "Retry webhooks", "spec": "exponential backoff", "area_id": backend.id},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    s = Slice.objects.get(title="Retry webhooks")
    assert s.spec == "exponential backoff" and s.area_id == backend.id


@pytest.mark.django_db
def test_capture_requires_title(client_local, org):
    resp = client_local.post(
        f"{P(org)}/capture", {"title": "   ", "spec": "orphan"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 400
    assert not Slice.objects.filter(spec="orphan").exists()


@pytest.mark.django_db
def test_capture_ignores_a_stale_status_or_tags_post(client_local, org):
    """status/tags는 이 폼에 없다. 옛 클라이언트나 손으로 만든 POST가 보내도
    400이 아니라 조용히 무시하고 create_slice의 기본값(status="open", 태그
    없음)이 적용된다."""
    backend = create_area(org, "Backend")
    resp = client_local.post(
        f"{P(org)}/capture",
        {"title": "stale client", "area_id": backend.id, "status": "shipped", "tags": ["x"]},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    s = Slice.objects.get(title="stale client")
    assert s.status == "open" and s.area_id == backend.id
    assert not s.tags.exists()


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
    assert not Slice.objects.filter(title="cross tenant").exists()


def _capture_form(page_html):
    """Just the capture <form>. The assertions below are about absence, and the
    shell renders other forms that legitimately DO carry status/tags — the
    onboarding widget embeds the new-Slice dialog on every page. Scanning the
    whole document would test those instead."""
    start = page_html.index('class="capture-modal capture-modal--full"')
    return page_html[start:page_html.index("</form>", start)]


@pytest.mark.django_db
def test_capture_modal_offers_no_status_or_tags_fields(client_local, org):
    """이 대화상자는 Title/Description/Area만 받는다. status/tags는 여기 없다
    — 만드는 순간 고르는 값이 아니라 Ship/Drop 같은 후속 행동의 결과다."""
    create_area(org, "Backend")
    form = _capture_form(client_local.get(f"{P(org)}/inbox/").content.decode())
    assert 'name="title"' in form
    assert 'name="spec"' in form
    assert 'name="area_id"' in form
    assert 'name="status"' not in form
    assert 'name="tags"' not in form
    # Inbox는 Area와 같은 층위가 아니다 — 드롭다운의 선택지가 될 수 없다, 대신
    # 비워두면 그리로 간다는 것을 옵션 자체가 말한다.
    assert ">Keep in Inbox<" in form
    assert ">Inbox<" not in form
    assert "Backend" in form


@pytest.mark.django_db
def test_slice_dialog_always_offers_tags_never_status(client_local, org):
    """Slice에 area는 항상 있으므로 Tags를 숨길 조건이 없다. Status는 더 나아가
    아예 사라졌다 — 상태는 Ship/Drop의 결과이지 만들 때 고르는 값이 아니다
    (A0). 예전에는 x-if="area"로 가려져 있었는데, 그 분기는 이 파일을 캡처
    모달과 공유하던 시절의 잔재다."""
    area = create_area(org, "Backend")
    body = client_local.get(f"{P(org)}/areas/{area.slug}/").content.decode()
    assert 'name="status"' not in body
    assert 'name="tags"' in body
    # 분기의 흔적이 남아 있으면 안 된다. Inbox는 옵션이 아니라 사이드바
    # 목적지이므로, 지워졌는지 볼 것은 그 <option> 마크업이지 단어가 아니다.
    assert 'x-if="area"' not in body
    assert '<option value="">Inbox</option>' not in body
    assert "spec-edit--tall" in body


# --- Who captured it (Slice.created_by) -------------------------------------
#
# The field was added by an explicit human decision during this branch (the
# design mockup's "captured by") and then written exactly once, by migration
# 0046's backfill. capture() did not pass it, MCP did not pass it, and both the
# panel and the Inbox row read `slice.source` — which only ever says
# human-vs-agent. In a shared org "captured by you" is wrong for everyone
# except the one person who typed it.


@pytest.mark.django_db
def test_capture_records_who_captured_it(client_local, org):
    from tuckit.core.models import User

    client_local.post(f"{P(org)}/capture", {"title": "누가 넣었나", "spec": "본문"})
    s = Slice.objects.get(title="누가 넣었나")
    assert s.created_by is not None
    assert s.created_by.user == User.objects.get(email="local@tuckit.local")
    assert s.created_by.org_id == org.id


@pytest.mark.django_db
def test_the_inbox_row_and_panel_name_the_capturer(client_local, org):
    client_local.post(f"{P(org)}/capture", {"title": "누가 넣었나", "spec": "본문"})
    s = Slice.objects.get(title="누가 넣었나")

    row = client_local.get(f"{P(org)}/inbox/").content.decode()
    assert '<span class="source-badge">local@tuckit.local</span>' in row

    panel = client_local.get(f"{P(org)}/slices/{s.id}/").content.decode()
    assert "by local@tuckit.local ·" in panel


@pytest.mark.django_db
def test_the_panel_falls_back_to_source_when_nobody_is_recorded(client_local, org, area):
    """0046 could not backfill every row, and a machine-token agent resolves to
    no member — so the fallback has to stay."""
    from tuckit.core.services.slices import create_slice

    s = create_slice(org, area=area, title="출처 미상", source="agent")
    assert s.created_by_id is None
    panel = client_local.get(f"{P(org)}/slices/{s.id}/").content.decode()
    assert '<span class="prop-val">agent</span>' in panel


@pytest.mark.django_db
def test_creating_a_slice_from_an_area_also_records_the_capturer(client_local, org, area):
    """The Area page's quick-add and the onboarding Slice modal both land here.
    Leaving them unwired would mean "Captured by" depended on which form you
    happened to use."""
    from tuckit.core.models import User

    client_local.post(
        f"{P(org)}/areas/{area.slug}/slices", {"title": "에어리어에서 만든 것"},
    )
    s = Slice.objects.get(title="에어리어에서 만든 것")
    assert s.created_by.user == User.objects.get(email="local@tuckit.local")
