import pytest

from tuckit.core.models import ApiToken
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite
from tuckit.core.services.plans import create_plan
from tuckit.core.services.onboarding import onboarding_state


@pytest.mark.django_db
def test_fresh_workspace_all_incomplete(org):
    st = onboarding_state(org)
    assert (st.has_area, st.has_slice, st.has_plan, st.has_bite, st.connected) == (
        False, False, False, False, False,
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
def test_plan_marks_has_plan(org):
    area = create_area(org, "Backend")
    sl = create_slice(area.org, area=area, title="Retry webhooks", status="open")
    create_plan(sl, title="Plan")
    st = onboarding_state(org)
    assert st.has_plan is True and st.has_bite is False and st.current == 4


@pytest.mark.django_db
def test_bite_marks_has_bite(org):
    area = create_area(org, "Backend")
    sl = create_slice(area.org, area=area, title="Retry webhooks", status="open")
    create_plan(sl, title="Plan")
    create_bite(sl, "Add backoff")
    st = onboarding_state(org)
    assert st.has_bite is True and st.current == 5


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
    s1 = create_slice(area.org, area=area, title="One", status="open")
    s2 = create_slice(area.org, area=area, title="Two", status="open")
    assert onboarding_state(org).newest_slice_id == s2.id


@pytest.mark.django_db
def test_all_done(org):
    from tuckit.core.models import ActivityEvent
    area = create_area(org, "Backend")
    sl = create_slice(area.org, area=area, title="Retry webhooks", status="open")
    create_plan(sl, title="Plan")
    create_bite(sl, "Add backoff")
    ActivityEvent.objects.create(
        org=org, actor="agent", verb="created",
        target_type="slice", target_id=sl.id, target_label=sl.title,
    )
    st = onboarding_state(org)
    assert st.done is True and st.completed == 5 and st.current == 0
