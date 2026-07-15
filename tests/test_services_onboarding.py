import pytest

from tuckit.core.models import ApiToken, Area
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite
from tuckit.core.services.onboarding import onboarding_state


@pytest.mark.django_db
def test_fresh_workspace_all_incomplete(workspace):
    st = onboarding_state(workspace)
    assert (st.has_area, st.has_slice, st.has_bite, st.connected) == (False, False, False, False)
    assert st.done is False and st.completed == 0 and st.current == 1


@pytest.mark.django_db
def test_area_marks_has_area(workspace):
    create_area(workspace, "Backend")
    st = onboarding_state(workspace)
    assert st.has_area is True and st.current == 2


@pytest.mark.django_db
def test_slice_marks_has_slice(workspace):
    area = create_area(workspace, "Backend")
    create_slice(area, "Retry webhooks", status="idea")
    st = onboarding_state(workspace)
    assert st.has_area is True and st.has_slice is True and st.current == 3


@pytest.mark.django_db
def test_bite_marks_has_bite(workspace):
    area = create_area(workspace, "Backend")
    sl = create_slice(area, "Retry webhooks", status="idea")
    create_bite(sl, "Add backoff")
    st = onboarding_state(workspace)
    assert st.has_bite is True and st.current == 4


@pytest.mark.django_db
def test_token_marks_has_key_not_connected(workspace):
    ApiToken.objects.create(workspace=workspace, name="a", token_hash="x")
    st = onboarding_state(workspace)
    assert st.has_key is True
    assert st.connected is False  # a key alone is not "connected"


@pytest.mark.django_db
def test_agent_activity_marks_connected(workspace):
    from tuckit.core.models import ActivityEvent
    ActivityEvent.objects.create(
        workspace=workspace, actor="agent", verb="created",
        target_type="slice", target_id=1, target_label="Retry webhooks",
    )
    st = onboarding_state(workspace)
    assert st.connected is True


@pytest.mark.django_db
def test_all_done(workspace):
    from tuckit.core.models import ActivityEvent
    area = create_area(workspace, "Backend")
    sl = create_slice(area, "Retry webhooks", status="planned")
    create_bite(sl, "Add backoff")
    ActivityEvent.objects.create(
        workspace=workspace, actor="agent", verb="created",
        target_type="slice", target_id=sl.id, target_label=sl.title,
    )
    st = onboarding_state(workspace)
    assert st.done is True and st.completed == 4 and st.current == 0
