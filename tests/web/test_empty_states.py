import pytest


@pytest.mark.django_db
def test_triage_empty_guides(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/triage/").content.decode()
    assert "Nothing to triage" in body
    assert "let your agent add one" in body


@pytest.mark.django_db
def test_in_progress_empty_is_english(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/in-progress/").content.decode()
    assert "Nothing in progress" in body
    # no Korean left in the empty copy
    assert "진행 중인" not in body


@pytest.mark.django_db
def test_roadmap_empty_is_guiding(client_local, workspace):
    p = f"/{workspace.org.slug}/{workspace.slug}"
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Nothing here yet" in body
