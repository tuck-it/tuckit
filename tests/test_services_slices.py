import pytest

from tuckit.core.models import Org
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import (
    create_slice,
    inbox_slices,
    list_slices,
    reorder_slice,
    set_slice_area,
    set_slice_status,
    update_slice,
)


@pytest.mark.django_db
def test_create_slice_defaults_and_append_order(area):
    a = create_slice(area.org, area=area, title="Auth")
    b = create_slice(area.org, area=area, title="Payments")
    assert a.status == "open"
    assert list(list_slices(area)) == [a, b]
    assert a.rank < b.rank


@pytest.mark.django_db
def test_create_slice_with_tags_and_agent_source(area):
    s = create_slice(area.org, area=area, title="Fix XSS", tags=["bug"], source="agent", status="open")
    assert s.source == "agent"
    assert {t.name for t in s.tags.all()} == {"bug"}


@pytest.mark.django_db
def test_create_slice_after_inserts_between(area):
    a = create_slice(area.org, area=area, title="A")
    c = create_slice(area.org, area=area, title="C")
    b = create_slice(area.org, area=area, title="B", after=a)
    assert list(list_slices(area)) == [a, b, c]


@pytest.mark.django_db
def test_list_slices_filters_by_status_and_tag(area):
    create_slice(area.org, area=area, title="Shipped one", status="shipped")
    open_bug = create_slice(area.org, area=area, title="Open bug", status="open", tags=["bug"])
    assert list(list_slices(area, status="open")) == [open_bug]
    assert list(list_slices(area, tag="bug")) == [open_bug]


@pytest.mark.django_db
def test_set_status_shipped_sets_completed_at(area):
    s = create_slice(area.org, area=area, title="Auth")
    set_slice_status(s, "shipped")
    s.refresh_from_db()
    assert s.status == "shipped"
    assert s.completed_at is not None
    set_slice_status(s, "open")
    s.refresh_from_db()
    assert s.completed_at is None


@pytest.mark.django_db
def test_update_slice_replaces_tags(area):
    s = create_slice(area.org, area=area, title="Auth", tags=["bug"])
    update_slice(s, title="Auth v2", tags=["chore"])
    s.refresh_from_db()
    assert s.title == "Auth v2"
    assert {t.name for t in s.tags.all()} == {"chore"}


@pytest.mark.django_db
def test_reorder_slice_moves_to_front(area):
    a = create_slice(area.org, area=area, title="A")
    b = create_slice(area.org, area=area, title="B")
    reorder_slice(b, before=a)
    assert list(list_slices(area)) == [b, a]


@pytest.mark.django_db
def test_create_slice_before_inserts_between(area):
    a = create_slice(area.org, area=area, title="A")
    c = create_slice(area.org, area=area, title="C")
    b = create_slice(area.org, area=area, title="B", before=c)
    assert list(list_slices(area)) == [a, b, c]


@pytest.mark.django_db
def test_slice_tags_never_leak_across_orgs(area):
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other_area = create_area(other_org, "Backend")
    s1 = create_slice(area.org, area=area, title="One", tags=["bug"])
    s2 = create_slice(other_area.org, area=other_area, title="Two", tags=["bug"])
    tag1 = s1.tags.get()
    tag2 = s2.tags.get()
    assert tag1.id != tag2.id
    assert tag1.org == area.org
    assert tag2.org == other_org


@pytest.mark.django_db
def test_set_slice_area_moves_and_reranks():
    org = Org.objects.create(name="Acme", slug="acme")
    inbox = create_area(org, "Inbox")
    backend = create_area(org, "Backend")
    s = create_slice(inbox.org, area=inbox, title="captured thing")
    set_slice_area(s, backend)
    s.refresh_from_db()
    assert s.area_id == backend.id
    assert list(list_slices(backend)) == [s]
    assert list(list_slices(inbox)) == []


@pytest.mark.django_db
def test_create_slice_allocates_sequential_number_per_org():
    org = Org.objects.create(name="Acme", slug="acme")
    a = create_area(org, "Backend")
    s1 = create_slice(a.org, area=a, title="One")
    s2 = create_slice(a.org, area=a, title="Two")
    assert (s1.number, s2.number) == (1, 2)
    org.refresh_from_db()
    assert org.next_slice_number == 3


@pytest.mark.django_db
def test_number_is_per_org_not_global():
    o1 = Org.objects.create(name="A", slug="a")
    o2 = Org.objects.create(name="B", slug="b")
    s1 = create_slice(o1, area=create_area(o1, "X"), title="s")
    s2 = create_slice(o2, area=create_area(o2, "Y"), title="s")
    assert s1.number == 1 and s2.number == 1


@pytest.mark.django_db
def test_update_slice_assign_by_email_and_clear():
    from django.contrib.auth import get_user_model
    from tuckit.core.models import OrgMember
    from tuckit.core.services.members import resolve_member

    org = Org.objects.create(name="Acme", slug="acme")
    u = get_user_model().objects.create_user(email="a@b.co", password="pw123456")
    m = OrgMember.objects.create(user=u, org=org, role="member")
    s = create_slice(org, area=create_area(org, "B"), title="Auth")

    update_slice(s, assignee="a@b.co", assignee_member=resolve_member(org, "a@b.co"))
    s.refresh_from_db()
    assert s.assignee_id == m.id

    update_slice(s, assignee="", assignee_member=resolve_member(org, ""))
    s.refresh_from_db()
    assert s.assignee_id is None


@pytest.mark.django_db
def test_query_slices_org_wide_and_text():
    from tuckit.core.services.slices import query_slices

    org = Org.objects.create(name="Acme", slug="acme")
    a1, a2 = create_area(org, "OSS"), create_area(org, "Cloud")
    create_slice(a1.org, area=a1, title="MCP search endpoint", spec="fuzzy find")
    create_slice(a2.org, area=a2, title="Billing webhook")
    all_ = query_slices(org)
    assert len(all_) == 2                      # org-wide, no area needed
    found = query_slices(org, query="webhook")
    assert [s.title for s in found] == ["Billing webhook"]
    in_spec = query_slices(org, query="fuzzy")
    assert [s.title for s in in_spec] == ["MCP search endpoint"]


@pytest.mark.django_db
def test_create_slice_external_key_is_idempotent():
    from tuckit.core.models import Slice

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "B")
    s1 = create_slice(area.org, area=area, title="Auth", external_key="branch/auth")
    s2 = create_slice(area.org, area=area, title="Auth v2", external_key="branch/auth")
    assert s1.id == s2.id                 # same key -> update, not duplicate
    s2.refresh_from_db()
    assert s2.title == "Auth v2"
    assert Slice.objects.filter(area__org=org).count() == 1   # no duplicate row


@pytest.mark.django_db
def test_create_slice_external_key_scoped_per_org():
    o1 = Org.objects.create(name="A", slug="a")
    o2 = Org.objects.create(name="B", slug="b")
    s1 = create_slice(o1, area=create_area(o1, "X"), title="one", external_key="k")
    s2 = create_slice(o2, area=create_area(o2, "Y"), title="two", external_key="k")
    assert s1.id != s2.id                 # same key in different orgs -> distinct


# --- Slice.org + per-org number uniqueness (0035) ---


@pytest.mark.django_db
def test_create_slice_denormalizes_org_from_area():
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    s = create_slice(area.org, area=area, title="S")
    assert s.org_id == org.id


@pytest.mark.django_db
def test_duplicate_number_in_one_org_is_rejected():
    from django.db import IntegrityError, transaction

    from tuckit.core.models import Slice

    org = Org.objects.create(name="Acme", slug="acme")
    a1 = create_area(org, "Backend")
    a2 = create_area(org, "Frontend")
    Slice.objects.create(area=a1, org=org, title="A", rank="m", number=7)
    # atomic() so the failed INSERT does not poison the test's outer transaction.
    with pytest.raises(IntegrityError), transaction.atomic():
        Slice.objects.create(area=a2, org=org, title="B", rank="n", number=7)


@pytest.mark.django_db
def test_same_number_in_different_orgs_is_allowed():
    from tuckit.core.models import Slice

    o1 = Org.objects.create(name="Acme", slug="acme")
    o2 = Org.objects.create(name="Beta", slug="beta")
    Slice.objects.create(area=create_area(o1, "X"), org=o1, title="A", rank="m", number=7)
    Slice.objects.create(area=create_area(o2, "Y"), org=o2, title="B", rank="m", number=7)
    assert Slice.objects.filter(number=7).count() == 2


@pytest.mark.django_db
def test_set_slice_area_still_refuses_cross_org_move():
    """The denormalized Slice.org is only safe because a slice's org cannot
    change. This guard predates the column — pin it so a future edit that
    relaxes it fails here instead of silently corrupting org."""
    from tuckit.core.services.exceptions import InvalidValue

    o1 = Org.objects.create(name="Acme", slug="acme")
    o2 = Org.objects.create(name="Beta", slug="beta")
    s = create_slice(o1, area=create_area(o1, "X"), title="S")
    with pytest.raises(InvalidValue):
        set_slice_area(s, create_area(o2, "Y"))


# --- stage feeders ---


@pytest.mark.django_db
def test_stage_counts_matches_annotation_on_the_same_slices():
    """The dropped-bite rule exists twice — once in Python via bite_progress,
    once as an ORM filter= in the annotation. Nothing but this test keeps the
    two from drifting apart."""
    from tuckit.core.models import Slice
    from tuckit.core.services.bites import create_bite
    from tuckit.core.services.slices import annotate_stage_counts, stage_counts

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")

    bare = create_slice(area.org, area=area, title="No bites", spec="design")
    mixed = create_slice(area.org, area=area, title="Mixed", spec="design")
    create_bite(mixed, "done one", status="done")
    create_bite(mixed, "todo one")
    create_bite(mixed, "dropped one", status="dropped")

    annotated = {s.id: s for s in annotate_stage_counts(Slice.objects.filter(area=area))}
    for s in (bare, mixed):
        a = annotated[s.id]
        assert stage_counts(s) == (a._bites_done, a._bites_total), s.title


@pytest.mark.django_db
def test_tags_on_a_slice_do_not_fan_out_the_bite_counts():
    """Bites hang directly off the Slice now, so the plans__bites nested join
    is gone — but tags is still a separate multi-valued join on the same
    queryset. Without distinct=True on every Count, N tags would multiply the
    bite counts by N, and the result is plausible enough to pass unnoticed."""
    from tuckit.core.models import Slice
    from tuckit.core.services.bites import create_bite
    from tuckit.core.services.slices import annotate_stage_counts

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    s = create_slice(area.org, area=area, title="Tagged", spec="design", tags=["bug", "urgent", "backend"])
    create_bite(s, "a")
    create_bite(s, "b", status="done")

    a = annotate_stage_counts(Slice.objects.filter(pk=s.pk))[0]
    assert (a._bites_done, a._bites_total) == (1, 2)


@pytest.mark.django_db
def test_stage_of_reports_the_workflow_position():
    from tuckit.core.services.bites import create_bite
    from tuckit.core.services.slices import stage_of

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")

    assert stage_of(create_slice(area.org, area=area, title="Blank")) == "needs_design"

    designed = create_slice(area.org, area=area, title="Designed", spec="design")
    assert stage_of(designed) == "needs_steps"

    create_bite(designed, "step")
    assert stage_of(designed) == "executing"


@pytest.mark.django_db
def test_stage_of_uses_the_annotation_without_extra_queries(django_assert_num_queries):
    """The whole reason annotate_stage_counts exists: a 50-row list must not
    issue two queries per row."""
    from tuckit.core.models import Slice
    from tuckit.core.services.slices import annotate_stage_counts, stage_of

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    for i in range(5):
        create_slice(area.org, area=area, title=f"S{i}", spec="design")

    rows = list(annotate_stage_counts(Slice.objects.filter(area=area)))
    with django_assert_num_queries(0):
        assert [stage_of(s) for s in rows] == ["needs_steps"] * 5


@pytest.mark.django_db
def test_query_slices_rows_carry_the_annotation():
    """list_slices reads stage off query_slices output, so the annotation has to
    survive that function's .distinct() and slicing."""
    from tuckit.core.services.slices import query_slices, stage_of

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    create_slice(area.org, area=area, title="One", spec="design")

    rows = query_slices(org)
    assert hasattr(rows[0], "_bites_total")
    assert stage_of(rows[0]) == "needs_steps"


@pytest.mark.django_db
def test_query_slices_keeps_rank_order_despite_the_annotation():
    """The stage annotation adds a GROUP BY, and Django does not apply
    Meta.ordering to aggregate queries — so rank order has to be asked for
    explicitly or it vanishes without any error."""
    from tuckit.core.services.slices import query_slices, update_slice

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    a = create_slice(area.org, area=area, title="A")
    b = create_slice(area.org, area=area, title="B")
    update_slice(b, before=a)

    assert [s.title for s in query_slices(org)] == ["B", "A"]


# --- Inbox: a slice with no area, and reversible filing (Task 6) ---


@pytest.mark.django_db
def test_create_slice_without_an_area_lands_in_the_inbox(org):
    s = create_slice(org, title="아직 모르겠음")
    assert s.area_id is None
    assert list(inbox_slices(org)) == [s]


@pytest.mark.django_db
def test_choosing_an_area_files_it_out_of_the_inbox(org, area):
    s = create_slice(org, title="캡처")
    set_slice_area(s, area)
    s.refresh_from_db()
    assert s.area_id == area.id
    assert list(inbox_slices(org)) == []


@pytest.mark.django_db
def test_clearing_the_area_returns_it_to_the_inbox(org, area):
    """가역성 회귀 가드 — 이것이 Promote 비가역성을 없앤 핵심이다."""
    s = create_slice(org, area=area, title="정리됨")
    set_slice_area(s, None)
    s.refresh_from_db()
    assert s.area_id is None
    assert list(inbox_slices(org)) == [s]


@pytest.mark.django_db
def test_inbox_excludes_dropped_and_shipped(org):
    s = create_slice(org, title="기각될 것")
    set_slice_status(s, "dropped")
    assert list(inbox_slices(org)) == []


@pytest.mark.django_db
def test_clearing_the_area_records_a_moved_event_to_inbox(org, area):
    """set_slice_area(slice_, None)이 활동 이벤트도 남기는지 확인한다 —
    반대 방향(영역 지정)과 대칭이어야 한다."""
    from tuckit.core.models import ActivityEvent

    s = create_slice(org, area=area, title="정리됨")
    ActivityEvent.objects.all().delete()
    set_slice_area(s, None, actor="agent")
    e = ActivityEvent.objects.get()
    assert e.verb == "moved" and e.actor == "agent"
    assert e.from_value == area.name and e.to_value == "Inbox"


@pytest.mark.django_db
def test_query_slices_excludes_inbox_by_default(org, area):
    from tuckit.core.services.slices import query_slices

    filed = create_slice(org, area=area, title="filed")
    create_slice(org, title="inbox item")
    assert query_slices(org) == [filed]
    assert {s.title for s in query_slices(org, include_inbox=True)} == {"filed", "inbox item"}


@pytest.mark.django_db
def test_inbox_filter_is_the_one_definition_both_readers_use(org, area):
    """inbox_slices() (the screen) and query_slices(inbox_only=True) (the MCP
    tool) must never disagree on membership. Sharing inbox_filter() is what
    guarantees it; this asserts the two actually return the same ids rather
    than merely calling something with the same name."""
    from tuckit.core.services.slices import inbox_slices, query_slices

    waiting = create_slice(org, title="still waiting")
    create_slice(org, area=area, title="filed")
    create_slice(org, title="shipped before triage", status="shipped")
    create_slice(org, title="dropped before triage", status="dropped")

    from_screen = {s.id for s in inbox_slices(org)}
    from_tool = {s.id for s in query_slices(org, inbox_only=True)}

    assert from_screen == from_tool == {waiting.id}
