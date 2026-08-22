"""Tests for mapping Slack-derived intents onto the tuckit service layer.

Every write here must go through tuckit.core.services.* (never the ORM
directly) and must resolve any model-supplied ref through
refs.parse_ref(org, ref) rather than hand-parsing it or treating it as a
primary key. See tuckit/integrations/slack/apply.py for the constraints
this suite enforces.
"""
import pytest

from tuckit.core.models import ActivityEvent, Slice
from tuckit.integrations.slack.apply import apply_intents
from tuckit.integrations.slack.interpret import Intent

pytestmark = pytest.mark.django_db


def test_create_slice_lands_in_the_named_area(org, member, area):
    results = apply_intents(org=org, member=member, intents=[
        Intent("create_slice", {"title": "A thing", "spec": "why", "area": area.slug}),
    ])
    assert results[0].ok is True
    created = Slice.objects.get(title="A thing")
    assert created.area == area
    assert created.source == "agent"


def test_empty_area_lands_in_the_inbox(org, member):
    apply_intents(org=org, member=member, intents=[
        Intent("create_slice", {"title": "Unfiled", "spec": "why", "area": ""}),
    ])
    assert Slice.objects.get(title="Unfiled").area is None


def test_add_note_resolves_a_ref_not_a_pk(org, member, slice_factory):
    target = slice_factory(title="Existing")
    ref = f"{org.key}-{target.number}"
    results = apply_intents(org=org, member=member, intents=[
        Intent("add_note", {"ref": ref, "body": "seen again"}),
    ])
    assert results[0].ok is True
    assert results[0].ref == ref


def test_a_ref_from_another_org_fails_without_touching_it(org, member, other_org_slice):
    bad_ref = f"{other_org_slice.org.key}-{other_org_slice.number}"
    results = apply_intents(org=org, member=member, intents=[
        Intent("add_note", {"ref": bad_ref, "body": "should not land"}),
    ])
    assert results[0].ok is False
    # Assert on the note specifically. The other org already has a "created"
    # event from building the fixture, so counting all its activity would pass
    # for the wrong reason.
    assert not ActivityEvent.objects.filter(
        target_type="slice", target_id=other_org_slice.id, verb="noted",
    ).exists()


def test_one_failure_does_not_roll_back_its_neighbours(org, member):
    results = apply_intents(org=org, member=member, intents=[
        Intent("create_slice", {"title": "First", "spec": "x", "area": ""}),
        Intent("add_note", {"ref": "NOPE-1", "body": "bad ref"}),
        Intent("create_slice", {"title": "Third", "spec": "x", "area": ""}),
    ])
    assert [r.ok for r in results] == [True, False, True]
    assert Slice.objects.filter(title__in=["First", "Third"]).count() == 2


def test_ask_clarification_writes_nothing(org, member):
    results = apply_intents(org=org, member=member, intents=[
        Intent("ask_clarification", {"question": "which one?"}),
    ])
    assert results[0].ok is False
    assert Slice.objects.count() == 0


def test_a_queue_retry_with_the_same_dedupe_key_does_not_duplicate_the_slice(org, member):
    """Cloud Tasks retries the whole job on any later failure (chat.update,
    a second intent, an exception past this point), calling apply_intents
    again with the identical intents and the identical dedupe_key. That
    retry bypasses the SlackEvent row that dedupes Slack's own retries (see
    apply_intents' docstring), so create_slice's external_key is the only
    thing standing between a retry and a second slice on the board -- the
    single worst failure mode this product exists to prevent. The retry must
    land on the SAME slice, not create a second one.
    """
    intents = [Intent("create_slice", {"title": "Retried thing", "spec": "why", "area": ""})]
    apply_intents(org=org, member=member, intents=intents, dedupe_key="slack:C123:111.222")
    apply_intents(org=org, member=member, intents=intents, dedupe_key="slack:C123:111.222")
    assert Slice.objects.filter(title="Retried thing").count() == 1


def test_apply_intents_does_not_share_one_transaction():
    """Rule 2 is "each intent commits independently" -- guard it directly.

    This is a static check, not a scenario, and that is a deliberate choice:
    tuckit's own service layer already contains most write failures behind a
    per-call savepoint (create_slice wraps its INSERT in its own
    transaction.atomic()), and record_activity's write only violates a real
    database constraint through a bad `member` FK, which apply_intents never
    lets an intent's args reach -- member always comes from the trusted
    caller. So no scenario reachable through legitimate intent args can make
    a single shared transaction.atomic() around the loop actually observable
    from the outside. Reading the source is the reliable way to lock in the
    invariant the docstring already promises.
    """
    import inspect

    from tuckit.integrations.slack import apply as apply_module

    source = inspect.getsource(apply_module.apply_intents)
    assert "atomic" not in source, (
        "apply_intents must not wrap its loop in transaction.atomic() -- "
        "partial success requires each intent to commit independently"
    )
