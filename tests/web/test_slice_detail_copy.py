"""The slice detail page (panel + full page share _slice_detail.html) labels the
spec field "Spec" and uses English UI copy — no leftover Korean."""
import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_slice_detail_labels_field_spec_not_description(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="labelled slice", spec="some detail")
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/slices/{s.id}/").content.decode()
    assert '<div class="section-label">Spec</div>' in body
    assert '<div class="section-label">Description</div>' not in body


@pytest.mark.django_db
def test_slice_detail_uses_english_copy(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="empty slice")  # no spec, no bites → empty states show
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/slices/{s.id}/").content.decode()
    # English replacements present (empty slice → the Steps empty state)
    assert "No steps yet" in body


@pytest.mark.django_db
def test_add_step_input_shows_an_example(client_local, org):
    """The add-step input teaches by example so a human knows what to type —
    obvious fields stay unadorned, this one does not. (The add-PLAN input it
    used to check alongside is gone: steps hang off the slice.)"""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Retry webhooks")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert "Write the retry unit test" in body
    # ...and the constraints field says what belongs in it, which is the only
    # place in the product that does.
    assert "landmines" in body
