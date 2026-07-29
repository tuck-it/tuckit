import pytest



@pytest.mark.django_db
def test_inbox_empty_guides(client_local, org):
    """Task 9: the Inbox lists Slices now, not Tickets — "Nothing to triage"
    implied a decision to make; filing an Area-less Slice has no decision left
    to defer, so the empty state says what happened instead ("everything is
    filed") rather than what to do next."""
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert "Inbox is empty. Everything is filed." in body


@pytest.mark.django_db
def test_roadmap_empty_is_guiding(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Nothing here yet" in body
