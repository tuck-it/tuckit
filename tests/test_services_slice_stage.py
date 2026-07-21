"""The stage decision table, exercised without a database.

Every input is a primitive, so these tests pin the rules themselves rather than
the queries that feed them. The feeders are tested separately in
test_services_slices.py.
"""

import pytest

from tuckit.core.services.slices import SLICE_STAGES, slice_stage


def test_every_documented_stage_is_reachable():
    reached = {
        slice_stage("shipped", "", 0, 0, 0),
        slice_stage("dropped", "", 0, 0, 0),
        slice_stage("planned", "", 0, 0, 0),
        slice_stage("planned", "design", 0, 0, 0),
        slice_stage("planned", "design", 1, 0, 0),
        slice_stage("planned", "design", 1, 1, 3),
        slice_stage("planned", "design", 1, 3, 3),
    }
    assert reached == set(SLICE_STAGES)


@pytest.mark.parametrize("status", ["shipped", "dropped"])
def test_finished_slices_report_their_status_not_a_next_step(status):  # design D1
    """A slice built without a design doc is a fact about history, not a to-do.
    Pure derivation would tell you to go brainstorm something already deployed."""
    assert slice_stage(status, "", 0, 0, 0) == status
    assert slice_stage(status, "design", 2, 1, 5) == status


def test_empty_spec_means_design_comes_first():
    assert slice_stage("planned", "", 0, 0, 0) == "needs_design"
    # even if someone made a plan before writing the design doc
    assert slice_stage("building", "", 3, 2, 4) == "needs_design"


def test_spec_without_a_plan_needs_a_plan():
    assert slice_stage("planned", "design", 0, 0, 0) == "needs_plan"


def test_empty_plan_needs_bites_not_ship():  # design D2
    """The 0-of-0 trap: `done == total` is vacuously true at zero, so the naive
    rule would call a slice with no work defined ready to ship."""
    assert slice_stage("planned", "design", 1, 0, 0) == "needs_bites"
    assert slice_stage("planned", "design", 2, 0, 0) == "needs_bites"


def test_outstanding_bites_mean_executing():
    assert slice_stage("building", "design", 1, 0, 3) == "executing"
    assert slice_stage("building", "design", 1, 2, 3) == "executing"


def test_all_bites_done_is_ready_to_ship():
    assert slice_stage("building", "design", 1, 3, 3) == "ready_to_ship"


def test_a_slice_whose_last_bite_was_dropped_is_ready_not_stuck():
    """bites_total excludes dropped bites, so dropping the last outstanding step
    finishes the slice instead of stranding it in executing forever."""
    # two bites, one done, one dropped -> caller passes (done=1, total=1)
    assert slice_stage("building", "design", 1, 1, 1) == "ready_to_ship"


def test_whitespace_only_spec_still_counts_as_written():
    """`not spec` is the rule; a spec someone deliberately filled with a space is
    theirs. This pins the boundary so nobody 'helpfully' adds .strip() later and
    silently reclassifies slices."""
    assert slice_stage("planned", " ", 0, 0, 0) == "needs_plan"
