import pytest
from django.apps import apps

from tuckit.core.models import ActivityEvent, Area, Bite, Org, OrgMember, Slice
from tuckit.core.services.export.schema import (
    EXCLUDED,
    EXCLUDED_MODELS,
    EXPORT_SCHEMA,
    SCHEMA_VERSION,
    covered_model_fields,
)

GUARDED = [Org, OrgMember, Area, Slice, Bite, ActivityEvent]


@pytest.mark.parametrize("model", GUARDED)
def test_every_concrete_field_is_exported_or_excluded_with_a_reason(model):
    """A new column must be declared in EXPORT_SCHEMA or excluded on purpose.

    This is the whole flexibility mechanism: without it, adding a field leaves
    the export quietly incomplete while every other test stays green.

    Many-to-many fields count. They were skipped here until TP-150 — not
    because Django hides them (Slice.tags reports concrete=True and even a
    column) but because this comprehension used to exclude them by hand.
    Slice.tags is exported as a list of names, so a second many-to-many is
    exactly as exportable and exactly as easy to forget.
    """
    concrete = {
        f.name for f in model._meta.get_fields()
        if getattr(f, "concrete", False)
    }
    uncovered = concrete - covered_model_fields(model)
    assert not uncovered, (
        f"{model.__name__} has fields the export does not know about: "
        f"{sorted(uncovered)}. Add them to EXPORT_SCHEMA in "
        f"tuckit/core/services/export/schema.py, or to EXCLUDED with a reason."
    )


@pytest.mark.parametrize("model", GUARDED)
def test_every_exclusion_states_a_reason(model):
    for name, reason in EXCLUDED.get(model, {}).items():
        assert reason.strip(), f"{model.__name__}.{name} is excluded with no reason"


@pytest.mark.parametrize("model", GUARDED)
def test_nothing_is_both_exported_and_excluded(model):
    """An entry in EXCLUDED claims a field is left out. If the schema also
    emits it, one of the two is a lie, and the reason text will mislead whoever
    reads it next."""
    emitted = set()
    for spec in EXPORT_SCHEMA.values():
        if spec.model is model:
            emitted |= (set(spec.fields) - set(spec.derived)) | set(spec.sources)
    overlap = emitted & set(EXCLUDED.get(model, {}))
    assert not overlap, f"{model.__name__}: {sorted(overlap)} is both exported and excluded"


@pytest.mark.parametrize("name,spec", EXPORT_SCHEMA.items())
def test_every_source_alias_points_at_a_real_field(name, spec):
    """A `sources` entry claims a model column is covered because it aliases to
    an output key in `fields`. If that output key is ever renamed or dropped
    from `fields` while the `sources` entry survives, the alias goes stale:
    `covered_model_fields()` would still count the model column as covered,
    even though nothing in EXPORT_SCHEMA actually emits it — the exact
    "quietly incomplete" failure the drift guard exists to catch.
    """
    dangling = set(spec.sources.values()) - set(spec.fields)
    assert not dangling, (
        f"{name}: sources alias to output keys missing from fields: "
        f"{sorted(dangling)}"
    )


def test_schema_version_is_one():
    assert SCHEMA_VERSION == 1


def test_schema_covers_the_five_documented_collections():
    assert set(EXPORT_SCHEMA) == {"members", "areas", "slices", "bites", "activity"}


def test_every_core_model_is_guarded_or_excluded_with_a_reason():
    """A model nobody classified is a model whose data nobody decided about.

    The field guard only looks at GUARDED, which is a hand-written literal, so
    an entirely new model is invisible to it. That is not hypothetical:
    ThrottleEpisode arrived while TP-146 was being landed and the suite stayed
    green. Leaving it out was right; nobody being asked was not.

    The comparison is two-way on purpose. A new model shows up only in `known`
    and fails; a deleted model lingers only in `accounted` and fails, which is
    what stops dead entries from piling up in a list nobody re-reads.
    """
    known = {m.__name__ for m in apps.get_app_config("core").get_models()}
    accounted = {m.__name__ for m in GUARDED} | {m.__name__ for m in EXCLUDED_MODELS}

    unclassified = known - accounted
    assert not unclassified, (
        f"These core models are neither exported nor excluded: "
        f"{sorted(unclassified)}. Add each to GUARDED in this file (and to "
        f"EXPORT_SCHEMA), or to EXCLUDED_MODELS in "
        f"tuckit/core/services/export/schema.py with a reason."
    )

    phantom = accounted - known
    assert not phantom, (
        f"These models are classified but no longer exist: {sorted(phantom)}. "
        f"Remove them from GUARDED or EXCLUDED_MODELS."
    )


def test_every_model_exclusion_states_a_reason():
    for model, reason in EXCLUDED_MODELS.items():
        assert reason.strip(), f"{model.__name__} is excluded with no reason"
