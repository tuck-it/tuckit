import pytest

from tuckit.core.models import ApiToken
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite
from tuckit.core.services.onboarding import onboarding_state


@pytest.mark.django_db
def test_onboarding_has_four_steps_without_the_plan_gate(org):
    """Task 7: the Plan step is gone, so onboarding is Area → Slice → Steps →
    Connect agent (4 steps, not 5). OnboardingState is a frozen dataclass, not
    a dict — `total`/`hasattr` are the real equivalents of the brief's
    illustrative `st["total"]`/`"has_plan" not in st` sketch."""
    st = onboarding_state(org)
    assert st.total == 4
    assert not hasattr(st, "has_plan")


@pytest.mark.django_db
def test_fresh_workspace_all_incomplete(org):
    st = onboarding_state(org)
    assert (st.has_area, st.has_slice, st.has_bite, st.connected) == (
        False, False, False, False,
    )
    assert st.done is False and st.completed == 0 and st.current == 1


@pytest.mark.django_db
def test_area_marks_has_area(org):
    create_area(org, "Backend")
    st = onboarding_state(org)
    assert st.has_area is True and st.current == 2


@pytest.mark.django_db
def test_slice_marks_has_slice(org):
    area = create_area(org, "Backend")
    create_slice(area.org, area=area, title="Retry webhooks", status="open")
    st = onboarding_state(org)
    assert st.has_area is True and st.has_slice is True and st.current == 3


@pytest.mark.django_db
def test_bite_marks_has_bite(org):
    area = create_area(org, "Backend")
    sl = create_slice(area.org, area=area, title="Retry webhooks", status="open")
    create_bite(sl, "Add backoff")
    st = onboarding_state(org)
    assert st.has_bite is True and st.current == 4


@pytest.mark.django_db
def test_token_marks_has_key_not_connected(org):
    ApiToken.objects.create(org=org, name="a", token_hash="x")
    st = onboarding_state(org)
    assert st.has_key is True
    assert st.connected is False  # a key alone is not "connected"


@pytest.mark.django_db
def test_agent_activity_marks_connected(org):
    from tuckit.core.models import ActivityEvent
    ActivityEvent.objects.create(
        org=org, actor="agent", verb="created",
        target_type="slice", target_id=1, target_label="Retry webhooks",
    )
    st = onboarding_state(org)
    assert st.connected is True


@pytest.mark.django_db
def test_newest_slice_id_tracks_latest(org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.onboarding import onboarding_state
    area = create_area(org, "Backend")
    assert onboarding_state(org).newest_slice_id is None
    create_slice(area.org, area=area, title="One", status="open")
    s2 = create_slice(area.org, area=area, title="Two", status="open")
    assert onboarding_state(org).newest_slice_id == s2.id


@pytest.mark.django_db
def test_newest_slice_id_skips_unfiled_captures(org):
    """Step 3의 링크 대상은 '스텝을 받을 수 있는' 슬라이스여야 한다.

    _slice_detail.html은 Steps 블록 전체를 `{% if slice.area %}`로 막는데,
    캡처는 area 없는 슬라이스를 만들고 그게 곧 '가장 최신'이다. 그래서 그냥
    최신 슬라이스를 고르면, 먼저 캡처한 첫 사용자는 Steps 폼이 아예 없는
    페이지로 보내진다."""
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.onboarding import onboarding_state
    area = create_area(org, "Backend")
    filed = create_slice(area.org, area=area, title="정리된 것", status="open")
    create_slice(org, title="방금 캡처한 것")           # area 없음 = 더 최신

    assert onboarding_state(org).newest_slice_id == filed.id


@pytest.mark.django_db
def test_newest_slice_id_is_none_when_nothing_is_filed_yet(org):
    """캡처만 한 상태 — 가리킬 대상이 없다. 위젯은 이때 '먼저 area를 골라라'를
    가르쳐야 하므로, 존재하지 않는 대상을 지어내지 않고 None을 낸다."""
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.onboarding import onboarding_state
    create_slice(org, title="방금 캡처한 것")

    st = onboarding_state(org)
    assert st.has_slice is True          # 캡처도 슬라이스다 — 2단계는 완료
    assert st.newest_slice_id is None    # ...하지만 스텝을 받을 슬라이스는 없다


@pytest.mark.django_db
def test_all_done(org):
    from tuckit.core.models import ActivityEvent
    area = create_area(org, "Backend")
    sl = create_slice(area.org, area=area, title="Retry webhooks", status="open")
    create_bite(sl, "Add backoff")
    ActivityEvent.objects.create(
        org=org, actor="agent", verb="created",
        target_type="slice", target_id=sl.id, target_label=sl.title,
    )
    st = onboarding_state(org)
    assert st.done is True and st.completed == 4 and st.current == 0
