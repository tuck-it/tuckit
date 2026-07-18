"""The slice detail page (panel + full page share _slice_panel.html) labels the
spec field "Spec" and uses English UI copy — no leftover Korean."""
import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_slice_detail_labels_field_spec_not_description(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a, "labelled slice", spec="some detail")
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/slices/{s.id}/").content.decode()
    assert '<div class="section-label">Spec</div>' in body
    assert '<div class="section-label">Description</div>' not in body


@pytest.mark.django_db
def test_slice_detail_uses_english_copy(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a, "empty slice")  # no spec, no bites → empty states show
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/slices/{s.id}/").content.decode()
    # English replacements present (empty slice → PLAN empty state)
    assert "No plan yet" in body


@pytest.mark.django_db
def test_add_plan_and_bite_inputs_show_examples(client_local, org):
    """The add-plan / add-bite inputs teach by example so a human knows what
    to type — obvious fields stay unadorned, these two do not."""
    from tuckit.core.services.plans import create_plan

    a = create_area(org, "Backend")
    s = create_slice(a, "Retry webhooks")
    create_plan(s, title="v1")  # a plan exists → the add-bite row renders
    body = client_local.get(f"/{org.slug}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    # add-plan input carries an example, not a bare "Plan title…"
    assert "v1 approach" in body
    # add-bite input carries an example step
    assert "Write the retry unit test" in body
