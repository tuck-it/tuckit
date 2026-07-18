import pytest
from datetime import timedelta
from django.utils import timezone
from tuckit.core.models import Slice
from tuckit.core.services.areas import create_area, get_or_create_triage
from tuckit.core.services.slices import create_slice
from tuckit.core.services.bites import create_bite
from tuckit.core.services.plans import create_plan


@pytest.mark.django_db
def test_attention_page_lists_stale_items(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a, "Stalled work", status="building")
    Slice.objects.filter(pk=s.pk).update(updated_at=timezone.now() - timedelta(days=9))
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/attention/").content.decode()
    assert "Stalled work" in body
    assert "9d idle" in body


@pytest.mark.django_db
def test_attention_page_all_clear_when_empty(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/attention/").content.decode()
    assert "all-clear" in body
    assert 'class="panel"' in body   # empty state is carded, not floating bare text


@pytest.mark.django_db
def test_in_progress_page_shows_building_and_doing(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a, "Building slice", status="building")
    create_bite(create_plan(s, title="Plan"), "Doing bite", status="doing")
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/in-progress/").content.decode()
    assert "Building slice" in body
    assert "Doing bite" in body


@pytest.mark.django_db
def test_roadmap_page_shows_distribution_and_slices(client_local, org):
    a = create_area(org, "Backend")
    create_slice(a, "Roadmap item", status="planned")
    create_slice(get_or_create_triage(org), "Stray note", status="idea")  # excluded
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert "Roadmap item" in body
    assert 'data-status="planned"' in body   # rendered in its status column
    assert "Stray note" not in body   # triage slices excluded from roadmap


@pytest.mark.django_db
def test_board_page_heading(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/roadmap/").content.decode()
    assert '<h1 class="page-title">Board</h1>' in body
