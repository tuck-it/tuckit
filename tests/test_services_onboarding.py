import pytest

from tuckit.core.models import Area, ApiToken
from tuckit.core.services.onboarding import onboarding_state
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_fresh_workspace_all_incomplete(workspace):
    st = onboarding_state(workspace)
    assert (st.connected, st.captured, st.triaged) == (False, False, False)
    assert st.done is False and st.completed == 0


@pytest.mark.django_db
def test_token_marks_connected(workspace):
    ApiToken.objects.create(workspace=workspace, name="a", token_hash="x")
    st = onboarding_state(workspace)
    assert st.connected is True and st.completed == 1


@pytest.mark.django_db
def test_slice_marks_captured_only_if_in_triage(workspace):
    triage = Area.objects.get(workspace=workspace, is_triage=True)
    create_slice(triage, "idea", status="idea")
    st = onboarding_state(workspace)
    assert st.captured is True and st.triaged is False


@pytest.mark.django_db
def test_slice_in_normal_area_marks_triaged(workspace):
    default = Area.objects.get(workspace=workspace, is_triage=False)
    create_slice(default, "real", status="planned")
    st = onboarding_state(workspace)
    assert st.captured is True and st.triaged is True


@pytest.mark.django_db
def test_all_done(workspace):
    ApiToken.objects.create(workspace=workspace, name="a", token_hash="x")
    default = Area.objects.get(workspace=workspace, is_triage=False)
    create_slice(default, "real", status="planned")
    st = onboarding_state(workspace)
    assert st.done is True and st.completed == 3
