"""The stage decision table, exercised without a database.

Every input is a primitive, so these tests pin the rules themselves rather than
the queries that feed them. The feeders are tested separately in
test_services_slices.py.
"""

import pytest

from tuckit.core.services.slices import SLICE_STAGES, slice_stage


def test_every_documented_stage_is_reachable():
    reached = {
        slice_stage("shipped", "", 0, 0),
        slice_stage("dropped", "", 0, 0),
        slice_stage("planned", "", 0, 0),
        slice_stage("planned", "design", 0, 0),
        slice_stage("planned", "design", 1, 3),
        slice_stage("planned", "design", 3, 3),
    }
    assert reached == set(SLICE_STAGES)


@pytest.mark.parametrize("status", ["shipped", "dropped"])
def test_finished_slices_report_their_status_not_a_next_step(status):  # design D1
    """A slice built without a design doc is a fact about history, not a to-do.
    Pure derivation would tell you to go brainstorm something already deployed."""
    assert slice_stage(status, "", 0, 0) == status
    assert slice_stage(status, "design", 1, 5) == status


def test_empty_spec_means_design_comes_first():
    assert slice_stage("planned", "", 0, 0) == "needs_design"
    # even if someone already added bites before writing the design doc
    assert slice_stage("building", "", 2, 4) == "needs_design"


def test_spec_without_bites_needs_steps():
    assert slice_stage("planned", "design", 0, 0) == "needs_steps"


def test_empty_bite_count_needs_steps_not_ship():  # design D2
    """The 0-of-0 trap: `done == total` is vacuously true at zero, so the naive
    rule would call a slice with no work defined ready to ship."""
    assert slice_stage("planned", "design", 0, 0) == "needs_steps"


def test_outstanding_bites_mean_executing():
    assert slice_stage("building", "design", 0, 3) == "executing"
    assert slice_stage("building", "design", 2, 3) == "executing"


def test_all_bites_done_is_ready_to_ship():
    assert slice_stage("building", "design", 3, 3) == "ready_to_ship"


def test_a_slice_whose_last_bite_was_dropped_is_ready_not_stuck():
    """bites_total excludes dropped bites, so dropping the last outstanding step
    finishes the slice instead of stranding it in executing forever."""
    # two bites, one done, one dropped -> caller passes (done=1, total=1)
    assert slice_stage("building", "design", 1, 1) == "ready_to_ship"


def test_whitespace_only_spec_still_counts_as_written():
    """`not spec` is the rule; a spec someone deliberately filled with a space is
    theirs. This pins the boundary so nobody 'helpfully' adds .strip() later and
    silently reclassifies slices."""
    assert slice_stage("planned", " ", 0, 0) == "needs_steps"


from tuckit.core.services.slices import BOARD_STAGE_COLUMNS, stage_column


def test_board_columns_map_to_themselves():
    for stage in ("needs_design", "needs_steps", "executing", "ready_to_ship", "shipped"):
        assert stage_column(stage) == stage


def test_dropped_is_not_a_board_column():
    assert stage_column("dropped") is None


def test_board_columns_are_the_four_pipeline_stages_in_order():
    assert BOARD_STAGE_COLUMNS == (
        "needs_design", "needs_steps", "executing", "ready_to_ship", "shipped",
    )


def test_needs_plan_and_needs_bites_no_longer_exist():
    """Regression guard — if the Plan layer comes back, this catches it."""
    assert "needs_plan" not in BOARD_STAGE_COLUMNS
    assert "needs_bites" not in BOARD_STAGE_COLUMNS
    assert "needs_steps" in BOARD_STAGE_COLUMNS


# --- delegation_prompt: the text a human hands to an agent -------------------

from tuckit.core.services.slices import delegation_prompt

_SKILL_FOR_STAGE = {
    "needs_design": "designing-a-slice",
    "needs_steps": "breaking-down-a-slice",
    "executing": "executing-a-slice",
    "ready_to_ship": "shipping-a-slice",
}


@pytest.mark.parametrize("stage,skill", sorted(_SKILL_FOR_STAGE.items()))
def test_prompt_names_the_slice_the_stage_and_the_stage_s_skill(stage, skill):
    """The three things the SessionStart primer cannot know: which slice, what
    stage it is at, and which skill that stage calls for."""
    out = delegation_prompt("TP-42", "Retry the webhook when Paddle times out", stage)
    assert "TP-42" in out
    assert "Retry the webhook when Paddle times out" in out
    assert 'get_slice("TP-42")' in out
    assert f"Stage is {stage} —" in out
    assert f"(skill: {skill})" in out


@pytest.mark.parametrize("stage", ["shipped", "dropped"])
def test_finished_slices_get_no_prompt_at_all(stage):
    """None, not "" — the template distinguishes "nothing to delegate" from a
    prompt that failed to build, and renders no control for the first."""
    assert delegation_prompt("TP-42", "Already done", stage) is None


def test_every_stage_is_handled():
    """Guard: a stage added to SLICE_STAGES without a sentence here would render
    a blank prompt in the panel, and nothing else would notice."""
    for stage in SLICE_STAGES:
        out = delegation_prompt("TP-1", "A title", stage)
        assert out is None or f"Stage is {stage} —" in out


def test_stage_name_appears_verbatim_not_prettified():
    """The plugin skills' descriptions key on the literal stage names ("stage
    reads needs_steps"), so "Needs steps" would weaken the trigger this whole
    feature exists to pull."""
    out = delegation_prompt("TP-42", "A title", "needs_steps")
    assert "needs_steps" in out
    assert "Needs steps" not in out


def test_the_ref_and_title_share_the_first_line():
    out = delegation_prompt("TP-42", "Retry the webhook", "executing")
    assert out.splitlines()[0] == "TP-42 — Retry the webhook"


def test_the_two_paragraphs_are_separated_by_a_blank_line():
    """The pasted prompt reads as a heading plus an instruction, not one blob."""
    head, sep, body = delegation_prompt("TP-42", "A title", "executing").partition("\n\n")
    assert sep, "expected a blank line between the title line and the instruction"
    assert body.startswith('Read it first: get_slice("TP-42")')


def test_the_prompt_points_at_the_board_instead_of_copying_it():
    """Design decision, pinned: inlining spec/constraints would be re-briefing,
    and a URL would invite scraping HTML over calling get_slice."""
    out = delegation_prompt("TP-42", "A title", "executing")
    assert "http" not in out
    assert "/slices/" not in out
