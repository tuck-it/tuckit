import pytest

from tuckit.core.models import ActivityEvent, Area, Bite, Org, OrgMember, Slice
from tuckit.core.services.export.schema import (
    EXCLUDED,
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
    """
    concrete = {
        f.name for f in model._meta.get_fields()
        if getattr(f, "concrete", False) and not f.many_to_many
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


def test_schema_version_is_one():
    assert SCHEMA_VERSION == 1


def test_schema_covers_the_five_documented_collections():
    assert set(EXPORT_SCHEMA) == {"members", "areas", "slices", "bites", "activity"}
