import pytest



@pytest.mark.django_db
def test_inbox_empty_guides(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert "Nothing to triage" in body
    assert "let your agent add one" in body


@pytest.mark.django_db
def test_roadmap_empty_is_guiding(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Nothing here yet" in body
