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


# --- Hand this slice to an agent -------------------------------------------
# The control renders the delegation prompt into the crumb. Its gate has four
# branches and each one is a separate way for the panel to be wrong, so each
# gets its own case. Every assertion is on the PROMPT TEXT, not on the icon:
# an icon assertion passes even when the prompt built empty.


@pytest.mark.django_db
def test_delegation_prompt_renders_for_a_filed_open_slice(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Retry webhooks", spec="design")  # spec, no bites → needs_steps
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert f'get_slice(&quot;{org.key}-{s.number}&quot;)' in body
    assert "Stage is needs_steps" in body
    assert "(skill: breaking-down-a-slice)" in body


@pytest.mark.django_db
def test_the_prompt_follows_the_slice_s_actual_stage(client_local, org):
    """An undesigned slice must be handed over as needs_design, or the agent is
    told to break down a spec that does not exist yet."""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Undesigned")  # no spec → needs_design
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "Stage is needs_design" in body
    assert "(skill: designing-a-slice)" in body
    assert "breaking-down-a-slice" not in body


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["shipped", "dropped"])
def test_no_delegation_prompt_on_a_finished_slice(client_local, org, status):
    """A finished slice has no next step to hand anyone."""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Done already", spec="design")
    s.status = status
    s.save(update_fields=["status"])
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "Read it first: get_slice" not in body
    assert "Hand to an agent" not in body


@pytest.mark.django_db
def test_no_delegation_prompt_on_an_unfiled_inbox_capture(client_local, org):
    """The unfiled panel deliberately opens ONE decision — where does this
    belong? The control appears the moment an area is picked."""
    s = create_slice(org, area=None, title="Unfiled thought", spec="design")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "Read it first: get_slice" not in body
    assert "Hand to an agent" not in body


@pytest.mark.django_db
def test_the_prompt_is_not_routed_through_a_js_string_literal(client_local, org):
    """A title carrying a quote must survive to the clipboard. The copy handler
    reads textContent off a <pre> for exactly this reason — an escapejs'd inline
    JS literal would break here."""
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title='Fix the "done" check', spec="design")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()
    assert "Fix the &quot;done&quot; check" in body
    assert "$refs.prompt.textContent" in body
