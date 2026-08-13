"""The single declaration of what an export contains.

Renderers read this, never the models. That indirection is what lets the drift
guard in tests/test_services_export_schema.py notice a new column: a field that
is neither declared here nor excluded below turns the suite red and names this
file.
"""
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable

from tuckit.core.models import ActivityEvent, Area, Bite, Org, OrgMember, Slice

# Bumped whenever the emitted shape changes in a way a reader could notice.
# This is the ONLY version stamped into an exported file: pyproject's version
# has not been bumped in ~50 releases (TP-118), so writing it would be a lie.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class EntitySpec:
    model: type
    # output key -> how to get it from one instance
    fields: dict[str, Callable[[Any], Any]]
    # output keys that are computed, not stored — they have no model column and
    # so must not be counted as covering one
    derived: tuple[str, ...] = ()
    # model column -> output key, for the cases where the two names differ.
    # A foreign key's Django field name is `area` while the natural output key
    # is `area_id`, so without this the guard would report `area` uncovered.
    sources: dict[str, str] = dc_field(default_factory=dict)


def _iso(value):
    return value.isoformat() if value is not None else None


def _email(member):
    # OrgMember.objects filters out ended memberships; forward FK access uses
    # the base manager (base_manager_name = "all_objects"), so someone who left
    # still resolves and history keeps its name.
    return member.user.email if member is not None else None


def _tags(slice_):
    return sorted(t.name for t in slice_.tags.all())


MEMBERS = EntitySpec(
    model=OrgMember,
    fields={
        "id": lambda m: m.id,
        "email": lambda m: m.user.email,
        "role": lambda m: m.role,
        "joined_at": lambda m: _iso(m.created_at),
        "ended_at": lambda m: _iso(m.ended_at),
    },
    sources={"user": "email", "created_at": "joined_at"},
)

AREAS = EntitySpec(
    model=Area,
    fields={
        "id": lambda a: a.id,
        "name": lambda a: a.name,
        "slug": lambda a: a.slug,
        "description": lambda a: a.description,
        "archived": lambda a: a.archived,
        "rank": lambda a: a.rank,
        "created_at": lambda a: _iso(a.created_at),
        "updated_at": lambda a: _iso(a.updated_at),
    },
)

SLICES = EntitySpec(
    model=Slice,
    fields={
        "id": lambda s: s.id,
        "ref": lambda s: s.export_ref,
        "number": lambda s: s.number,
        "area_id": lambda s: s.area_id,
        "title": lambda s: s.title,
        "spec": lambda s: s.spec,
        "constraints": lambda s: s.constraints,
        "status": lambda s: s.status,
        "stage": lambda s: s.export_stage,
        "tags": _tags,
        "assignee": lambda s: _email(s.assignee),
        "created_by": lambda s: _email(s.created_by),
        "source": lambda s: s.source,
        "external_key": lambda s: s.external_key,
        "duplicate_of": lambda s: s.duplicate_of_id,
        "rank": lambda s: s.rank,
        "bites_done": lambda s: s.export_bites_done,
        "bites_total": lambda s: s.export_bites_total,
        "created_at": lambda s: _iso(s.created_at),
        "updated_at": lambda s: _iso(s.updated_at),
        "completed_at": lambda s: _iso(s.completed_at),
    },
    derived=("ref", "stage", "bites_done", "bites_total"),
    # `assignee` and `created_by` need no entry: the model field and the output
    # key share a name, so they are already covered. Only `area` is renamed.
    sources={"area": "area_id"},
)

BITES = EntitySpec(
    model=Bite,
    fields={
        "id": lambda b: b.id,
        "slice_id": lambda b: b.slice_id,
        "title": lambda b: b.title,
        "body": lambda b: b.body,
        "status": lambda b: b.status,
        "source": lambda b: b.source,
        "rank": lambda b: b.rank,
        "created_at": lambda b: _iso(b.created_at),
        "updated_at": lambda b: _iso(b.updated_at),
    },
    sources={"slice": "slice_id"},
)

ACTIVITY = EntitySpec(
    model=ActivityEvent,
    fields={
        "id": lambda e: e.id,
        "source": lambda e: e.source,
        "member": lambda e: _email(e.member),
        "verb": lambda e: e.verb,
        "target_type": lambda e: e.target_type,
        "target_id": lambda e: e.target_id,
        "target_label": lambda e: e.target_label,
        "from_value": lambda e: e.from_value,
        "to_value": lambda e: e.to_value,
        "body": lambda e: e.body,
        "created_at": lambda e: _iso(e.created_at),
    },
)

EXPORT_SCHEMA: dict[str, EntitySpec] = {
    "members": MEMBERS,
    "areas": AREAS,
    "slices": SLICES,
    "bites": BITES,
    "activity": ACTIVITY,
}

# Columns not emitted as a row field. Each reason is load-bearing: the guard
# refuses a blank one, so "we forgot" can never masquerade as "we decided".
#
# Org has no EntitySpec at all — it is the envelope, not a collection — so every
# one of its columns is accounted for here, including the four the envelope
# itself carries.
EXCLUDED: dict[type, dict[str, str]] = {
    Org: {
        "id": "Internal surrogate key; the org is identified by slug and key.",
        "name": "Carried in the envelope's org block, not as a row.",
        "slug": "Carried in the envelope's org block.",
        "key": "Carried in the envelope's org block — it is the prefix in every ref.",
        "description": "Carried in the envelope's org block.",
        "onboarding_dismissed": "UI state for the first-run widget, not project data.",
        "onboarding_completed": "Same — first-run UI state.",
        "shipped_board_mode": "A board display preference, not something a team needs back.",
        "shipped_board_limit": "Same display preference.",
        "next_slice_number": "An allocator counter; meaningless outside this database.",
        "created_at": "The envelope carries exported_at; the org's own birthday adds nothing.",
        "updated_at": "Row bookkeeping.",
    },
    OrgMember: {
        "org": "Every row in the file belongs to the one org named in the envelope.",
        "home_seen_at": "A per-person read watermark for Home. Private UI state, not project data.",
    },
    Area: {"org": "Implied by the envelope."},
    Slice: {
        "org": "Implied by the envelope. The column is a denormalized projection of area.org.",
    },
    Bite: {},
    ActivityEvent: {"org": "Implied by the envelope."},
}


def covered_model_fields(model: type) -> set[str]:
    """Concrete field names on `model` that the export accounts for.

    A name counts if an EntitySpec emits it (directly, or renamed via
    `sources`) or if EXCLUDED states why it is left out.
    """
    covered = set(EXCLUDED.get(model, {}))
    for spec in EXPORT_SCHEMA.values():
        if spec.model is not model:
            continue
        covered |= set(spec.fields) - set(spec.derived)
        covered |= set(spec.sources)
    return covered
