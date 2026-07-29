"""0045가 데이터를 잃지 않는지 검증한다.

실운영에서 한 번만 돌고 되돌릴 수 없는 마이그레이션이라, 눈으로 읽어 확인하는
방식이 통하지 않는다. django_test_migrations의 Migrator로 0044 상태의 DB를
만들고, 0045를 실제로 적용한 뒤 결과를 읽는다.

Migrator.apply_initial_migration()은 모델 테이블을 전부 드롭하고 대상까지
'앞으로만' 재생한다 — 그래서 backward()가 예외를 던져도 이 테스트들은 돈다.
"""

import importlib
from datetime import timedelta

import pytest
from django.db import migrations
from django.utils import timezone
from django_test_migrations.migrator import Migrator

from tuckit.core.ranking import rank_between

BEFORE = ("core", "0044_two_layer_schema")
AFTER = ("core", "0045_fold_tickets_and_plans")


def _resolved():
    """티켓의 ticket_resolved_at_matches_status 체크 제약을 만족시키는 시각.

    open이 아닌 티켓은 resolved_at이 반드시 있어야 INSERT가 통과한다."""
    return timezone.now()


@pytest.mark.django_db
def test_open_ticket_becomes_open_slice_keeping_its_number(migrator: Migrator):
    old = migrator.apply_initial_migration(BEFORE)
    Org, Area = old.apps.get_model("core", "Org"), old.apps.get_model("core", "Area")
    Ticket = old.apps.get_model("core", "Ticket")

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    area = Area.objects.create(org=org, name="A", slug="a", rank="m")
    Ticket.objects.create(
        org=org, area=area, title="열린 캡처", body="본문", status="open",
        number=7, rank="m", source="human",
    )

    new = migrator.apply_tested_migration(AFTER)
    Slice = new.apps.get_model("core", "Slice")

    s = Slice.objects.get(number=7)
    assert s.title == "열린 캡처"
    assert s.spec == "본문"
    assert s.status == "open"
    assert s.area_id == area.id          # area는 살린다 (설계 결정)
    assert s.source == "human"


@pytest.mark.django_db
def test_promoted_ticket_does_not_create_a_second_slice(migrator: Migrator):
    """승격된 티켓과 그 슬라이스는 같은 number를 쓴다. 또 만들면 유니크 제약 위반."""
    old = migrator.apply_initial_migration(BEFORE)
    Org, Area = old.apps.get_model("core", "Org"), old.apps.get_model("core", "Area")
    Ticket = old.apps.get_model("core", "Ticket")
    Slice = old.apps.get_model("core", "Slice")

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    area = Area.objects.create(org=org, name="A", slug="a", rank="m")
    sl = Slice.objects.create(org=org, area=area, title="일감", spec="설계", rank="m", number=3)
    Ticket.objects.create(
        org=org, area=area, title="원본 캡처", body="원래 본문", status="promoted",
        number=3, rank="m", slice=sl, resolved_at=_resolved(),
    )

    new = migrator.apply_tested_migration(AFTER)
    NewSlice = new.apps.get_model("core", "Slice")

    assert NewSlice.objects.filter(number=3).count() == 1
    spec = NewSlice.objects.get(number=3).spec
    assert "원래 본문" in spec        # 본문이 소멸하지 않는다 (v0.28.0부터 복사가 아니라 링크)
    assert "설계" in spec             # 슬라이스가 원래 갖고 있던 스펙도 남는다


@pytest.mark.django_db
def test_absorbed_tickets_all_keep_their_bodies(migrator: Migrator):
    """한 슬라이스에 여러 티켓이 붙는다(absorb_ticket). 마지막 하나만 남으면 안 된다."""
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Ticket = old.apps.get_model("core", "Ticket")
    Slice = old.apps.get_model("core", "Slice")

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    sl = Slice.objects.create(org=org, title="일감", spec="설계", rank="m", number=3)
    Ticket.objects.create(
        org=org, title="원본", body="첫 캡처", status="promoted",
        number=3, rank="m", slice=sl, resolved_at=_resolved(),
    )
    Ticket.objects.create(
        org=org, title="흡수됨", body="둘째 캡처", status="promoted",
        number=4, rank="n", slice=sl, resolved_at=_resolved(),
    )

    new = migrator.apply_tested_migration(AFTER)
    NewSlice = new.apps.get_model("core", "Slice")

    spec = NewSlice.objects.get(number=3).spec
    assert "설계" in spec
    assert "첫 캡처" in spec
    assert "둘째 캡처" in spec
    assert NewSlice.objects.count() == 1     # 흡수된 티켓은 새 슬라이스를 만들지 않는다


@pytest.mark.django_db
def test_dismissed_and_duplicate_tickets_become_dropped_slices(migrator: Migrator):
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Ticket = old.apps.get_model("core", "Ticket")
    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    Ticket.objects.create(
        org=org, title="기각", body="", status="dismissed", number=1, rank="m",
        resolved_at=_resolved(),
    )
    Ticket.objects.create(
        org=org, title="중복", body="", status="duplicate", number=2, rank="n",
        resolved_at=_resolved(),
    )

    new = migrator.apply_tested_migration(AFTER)
    Slice = new.apps.get_model("core", "Slice")
    assert Slice.objects.get(number=1).status == "dropped"
    assert Slice.objects.get(number=2).status == "dropped"
    # dropped는 완료가 아니다 — _apply_status()와 같은 규칙을 지킨다.
    assert Slice.objects.get(number=1).completed_at is None


@pytest.mark.django_db
def test_ticket_creation_time_is_carried_over(migrator: Migrator):
    """created_at이 마이그레이션 시각으로 밀리면 52개 캡처가 전부 '오늘'이 된다."""
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Ticket = old.apps.get_model("core", "Ticket")
    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    t = Ticket.objects.create(org=org, title="오래된 캡처", body="", status="open", number=1, rank="m")
    old_ts = timezone.now() - timedelta(days=200)
    Ticket.objects.filter(pk=t.pk).update(created_at=old_ts)

    new = migrator.apply_tested_migration(AFTER)
    Slice = new.apps.get_model("core", "Slice")
    assert Slice.objects.get(number=1).created_at == old_ts


@pytest.mark.django_db
def test_plan_content_moves_onto_the_slice_and_bites_reparent(migrator: Migrator):
    old = migrator.apply_initial_migration(BEFORE)
    Org, Area = old.apps.get_model("core", "Org"), old.apps.get_model("core", "Area")
    Slice, Plan, Bite = (old.apps.get_model("core", n) for n in ("Slice", "Plan", "Bite"))

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    area = Area.objects.create(org=org, name="A", slug="a", rank="m")
    sl = Slice.objects.create(org=org, area=area, title="s", spec="설계", rank="m", number=1)
    p = Plan.objects.create(slice=sl, title="계획", body="접근", constraints="지뢰")
    Bite.objects.create(plan=p, title="단계1", rank="m")

    new = migrator.apply_tested_migration(AFTER)
    NewSlice, NewBite = new.apps.get_model("core", "Slice"), new.apps.get_model("core", "Bite")

    s = NewSlice.objects.get(number=1)
    assert s.constraints == "지뢰"
    assert "접근" in s.spec
    assert "설계" in s.spec
    assert NewBite.objects.get(title="단계1").slice_id == s.id


@pytest.mark.django_db
def test_multiple_plans_on_one_slice_are_concatenated_not_overwritten(migrator: Migrator):
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Slice, Plan, Bite = (old.apps.get_model("core", n) for n in ("Slice", "Plan", "Bite"))

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    sl = Slice.objects.create(org=org, title="s", spec="설계", rank="m", number=1)
    p1 = Plan.objects.create(slice=sl, title="계획1", body="접근1", constraints="제약1")
    p2 = Plan.objects.create(slice=sl, title="계획2", body="접근2", constraints="제약2")
    Bite.objects.create(plan=p1, title="1-a", rank="m")
    Bite.objects.create(plan=p1, title="1-b", rank="n")
    Bite.objects.create(plan=p2, title="2-a", rank="m")

    new = migrator.apply_tested_migration(AFTER)
    NewSlice, NewBite = new.apps.get_model("core", "Slice"), new.apps.get_model("core", "Bite")

    s = NewSlice.objects.get(number=1)
    assert "접근1" in s.spec and "접근2" in s.spec
    assert "제약1" in s.constraints and "제약2" in s.constraints
    assert s.spec.index("접근1") < s.spec.index("접근2")     # plan id 순서를 지킨다

    bites = list(NewBite.objects.filter(slice_id=s.id).order_by("rank"))
    assert [b.title for b in bites] == ["1-a", "1-b", "2-a"]
    ranks = [b.rank for b in bites]
    assert len(set(ranks)) == 3                              # 계획끼리 rank가 겹치지 않는다


@pytest.mark.django_db
def test_reparented_bite_ranks_stay_valid_fractional_index_keys(migrator: Migrator):
    """rank는 fractional-indexing 키다. '000001' 같은 값으로 덮으면 이후
    rank_between()이 FIError로 죽어 바이트를 하나도 더 못 넣는다."""
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Slice, Plan, Bite = (old.apps.get_model("core", n) for n in ("Slice", "Plan", "Bite"))

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    sl = Slice.objects.create(org=org, title="s", rank="m", number=1)
    p = Plan.objects.create(slice=sl, title="계획", body="접근")
    r = None
    for i in range(3):
        r = rank_between(r, None)
        Bite.objects.create(plan=p, title=f"b{i}", rank=r)

    new = migrator.apply_tested_migration(AFTER)
    NewBite = new.apps.get_model("core", "Bite")

    ranks = [b.rank for b in NewBite.objects.filter(slice_id=sl.id).order_by("rank")]
    assert ranks == sorted(ranks)
    # 마지막 rank 뒤에 새 바이트를 붙일 수 있어야 한다.
    appended = rank_between(ranks[-1], None)
    assert appended > ranks[-1]
    # 사이에도 끼울 수 있어야 한다.
    assert ranks[0] < rank_between(ranks[0], ranks[1]) < ranks[1]


@pytest.mark.django_db
def test_activity_events_are_retargeted_to_the_new_slice(migrator: Migrator):
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Ticket = old.apps.get_model("core", "Ticket")
    Activity = old.apps.get_model("core", "ActivityEvent")
    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    t = Ticket.objects.create(org=org, title="캡처", body="", status="open", number=1, rank="m")
    Activity.objects.create(
        org=org, actor="human", verb="created",
        target_type="ticket", target_id=t.id, target_label="캡처",
    )

    new = migrator.apply_tested_migration(AFTER)
    Slice = new.apps.get_model("core", "Slice")
    NewActivity = new.apps.get_model("core", "ActivityEvent")

    s = Slice.objects.get(number=1)
    e = NewActivity.objects.get(target_label="캡처")
    assert e.target_type == "slice"
    assert e.target_id == s.id


@pytest.mark.django_db
def test_activity_events_on_promoted_tickets_point_at_the_existing_slice(migrator: Migrator):
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Ticket = old.apps.get_model("core", "Ticket")
    Slice = old.apps.get_model("core", "Slice")
    Activity = old.apps.get_model("core", "ActivityEvent")

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    sl = Slice.objects.create(org=org, title="일감", rank="m", number=3)
    t = Ticket.objects.create(
        org=org, title="캡처", body="", status="promoted", number=3, rank="m",
        slice=sl, resolved_at=_resolved(),
    )
    Activity.objects.create(
        org=org, actor="human", verb="promoted",
        target_type="ticket", target_id=t.id, target_label="캡처",
    )

    new = migrator.apply_tested_migration(AFTER)
    NewActivity = new.apps.get_model("core", "ActivityEvent")
    e = NewActivity.objects.get(target_label="캡처")
    assert e.target_type == "slice"
    assert e.target_id == sl.id


@pytest.mark.django_db
def test_external_key_collision_clears_the_incoming_value(migrator: Migrator):
    old = migrator.apply_initial_migration(BEFORE)
    Org, Area = old.apps.get_model("core", "Org"), old.apps.get_model("core", "Area")
    Slice = old.apps.get_model("core", "Slice")
    Ticket = old.apps.get_model("core", "Ticket")
    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    area = Area.objects.create(org=org, name="A", slug="a", rank="m")
    Slice.objects.create(org=org, area=area, title="기존", rank="m", number=1, external_key="dup")
    Ticket.objects.create(
        org=org, area=area, title="충돌", body="", status="open",
        number=2, rank="n", external_key="dup",
    )

    new = migrator.apply_tested_migration(AFTER)
    NewSlice = new.apps.get_model("core", "Slice")
    moved = NewSlice.objects.get(number=2)
    assert moved.external_key == ""
    assert "migrated-external-key: dup" in moved.spec


@pytest.mark.django_db
def test_linked_ticket_external_key_moves_onto_its_slice(migrator: Migrator):
    """promote/absorb는 external_key를 슬라이스로 복사하지 않는다. 티켓 행이
    유일한 사본이라, 안 옮기면 0046이 테이블을 지울 때 같이 사라진다."""
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Slice = old.apps.get_model("core", "Slice")
    Ticket = old.apps.get_model("core", "Ticket")

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    sl = Slice.objects.create(org=org, title="일감", rank="m", number=3)   # external_key 없음
    Ticket.objects.create(
        org=org, title="원본", body="캡처", status="promoted", number=3, rank="m",
        slice=sl, external_key="JIRA-1", resolved_at=_resolved(),
    )

    new = migrator.apply_tested_migration(AFTER)
    NewSlice = new.apps.get_model("core", "Slice")
    assert NewSlice.objects.get(number=3).external_key == "JIRA-1"


@pytest.mark.django_db
def test_linked_ticket_external_key_that_would_collide_is_noted_not_assigned(migrator: Migrator):
    """org 안에서 그 키가 이미 쓰였으면 uniq_slice_external_key_per_org를 깨는
    대신 spec에 흔적을 남긴다 — 2번 루프가 미연결 티켓에 하는 것과 같은 처리."""
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Slice = old.apps.get_model("core", "Slice")
    Ticket = old.apps.get_model("core", "Ticket")

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    Slice.objects.create(org=org, title="선점", rank="l", number=1, external_key="JIRA-1")
    target = Slice.objects.create(org=org, title="일감", rank="m", number=3)
    Ticket.objects.create(
        org=org, title="원본", body="캡처", status="promoted", number=3, rank="m",
        slice=target, external_key="JIRA-1", resolved_at=_resolved(),
    )

    new = migrator.apply_tested_migration(AFTER)
    NewSlice = new.apps.get_model("core", "Slice")
    moved = NewSlice.objects.get(number=3)
    assert moved.external_key == ""
    assert "migrated-external-key: JIRA-1" in moved.spec
    assert "캡처" in moved.spec                                    # 본문도 그대로 남는다
    assert NewSlice.objects.get(number=1).external_key == "JIRA-1"  # 선점 쪽은 안 건드린다


@pytest.mark.django_db
def test_two_linked_tickets_with_the_same_slice_only_hand_over_one_key(migrator: Migrator):
    """absorb로 한 슬라이스에 티켓이 둘 붙고 둘 다 external_key를 갖는 경우.
    슬라이스 컬럼은 하나뿐이라, 먼저 온 쪽이 차지하고 나머지는 주석이 된다."""
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Slice = old.apps.get_model("core", "Slice")
    Ticket = old.apps.get_model("core", "Ticket")

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    sl = Slice.objects.create(org=org, title="일감", rank="m", number=3)
    Ticket.objects.create(
        org=org, title="원본", body="", status="promoted", number=3, rank="m",
        slice=sl, external_key="JIRA-1", resolved_at=_resolved(),
    )
    Ticket.objects.create(
        org=org, title="흡수", body="", status="promoted", number=4, rank="n",
        slice=sl, external_key="JIRA-2", resolved_at=_resolved(),
    )

    new = migrator.apply_tested_migration(AFTER)
    s = new.apps.get_model("core", "Slice").objects.get(number=3)
    assert s.external_key == "JIRA-1"
    assert "migrated-external-key: JIRA-2" in s.spec


@pytest.mark.django_db
def test_promoted_ticket_whose_slice_vanished_does_not_resurrect_as_open(migrator: Migrator):
    """Area를 지우면 슬라이스는 cascade로 죽고 Ticket.slice는 SET_NULL이라
    'promoted 인데 slice가 없는' 티켓이 남는다. open으로 떨어뜨리면 이미 답이
    나온 캡처가 인박스에 살아 있는 일감으로 되살아난다."""
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Ticket = old.apps.get_model("core", "Ticket")

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    Ticket.objects.create(
        org=org, title="슬라이스가 사라진 캡처", body="본문", status="promoted",
        number=5, rank="m", slice=None, resolved_at=_resolved(),
    )

    new = migrator.apply_tested_migration(AFTER)
    s = new.apps.get_model("core", "Slice").objects.get(number=5)
    assert s.status == "dropped"
    assert s.spec == "본문"          # 본문은 그래도 살린다


# NOTE: status_map의 기본값('open')은 DB를 통해 테스트할 수 없다.
# ticket_resolved_at_matches_status가 status 화이트리스트를 겸해서
# (models/domain.py의 주석 참고) 네 값 밖의 status는 UPDATE조차 막힌다:
#   IntegrityError: CHECK constraint failed: ticket_resolved_at_matches_status
# 그래서 기본값은 도달 불가능한 방어선이다 — 그대로 둔다.


@pytest.mark.django_db
def test_two_colliding_tickets_do_not_collide_with_each_other(migrator: Migrator):
    """티켓끼리 같은 external_key를 갖는 일은 없지만(유니크 제약), 슬라이스와
    겹치는 티켓이 둘이면 둘 다 비워야 한다 — 하나만 비우면 두 번째가 터진다."""
    old = migrator.apply_initial_migration(BEFORE)
    Org = old.apps.get_model("core", "Org")
    Slice = old.apps.get_model("core", "Slice")
    Ticket = old.apps.get_model("core", "Ticket")
    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    Slice.objects.create(org=org, title="기존", rank="m", number=1, external_key="dup")
    Ticket.objects.create(
        org=org, title="충돌1", body="", status="open", number=2, rank="n", external_key="dup",
    )
    Ticket.objects.create(
        org=org, title="충돌2", body="", status="open", number=3, rank="o", external_key="other",
    )

    new = migrator.apply_tested_migration(AFTER)
    NewSlice = new.apps.get_model("core", "Slice")
    assert NewSlice.objects.get(number=2).external_key == ""
    assert NewSlice.objects.get(number=3).external_key == "other"   # 안 겹치면 승계한다


def test_order_key_stays_sorted_and_valid_past_the_62_boundary():
    """한 슬라이스에 바이트가 62개를 넘으면 head가 'a'에서 'b'로 넘어간다.
    실데이터로는 잘 안 밟는 경로라 여기서 직접 밟는다."""
    mod = importlib.import_module("tuckit.core.migrations.0045_fold_tickets_and_plans")
    keys = [mod._order_key(i) for i in range(130)]
    assert keys[:3] == ["a0", "a1", "a2"]
    assert keys[61] == "az" and keys[62] == "b00"
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    # 마지막 뒤에 붙이는 것도, 사이에 끼우는 것도 되어야 한다.
    assert rank_between(keys[-1], None) > keys[-1]
    assert keys[61] < rank_between(keys[61], keys[62]) < keys[62]


def test_backward_refuses_to_run():
    """조용한 no-op이면 누군가 되돌릴 수 있다고 믿는다. 명시적으로 막는다.

    함수를 직접 부르는 것만으로는 부족하다 — RunPython에 실제로 물려 있지
    않으면 `migrate core 0044`는 여전히 조용히 성공한다. 배선까지 단언한다."""
    mod = importlib.import_module("tuckit.core.migrations.0045_fold_tickets_and_plans")
    with pytest.raises(RuntimeError, match="되돌릴 수 없다"):
        mod.backward(None, None)

    run_pythons = [
        op for op in mod.Migration.operations
        if isinstance(op, migrations.RunPython)
    ]
    assert run_pythons, "0045에 RunPython이 없다"
    assert all(op.reverse_code is mod.backward for op in run_pythons), (
        "backward()가 RunPython.reverse_code에 물려 있지 않다 — 되감기가 조용히 성공한다"
    )


# --- 0046: created_by 백필 -------------------------------------------------

BEFORE_0046 = ("core", "0045_fold_tickets_and_plans")
AFTER_0046 = ("core", "0046_schema_repair")


@pytest.mark.django_db
def test_created_by_is_backfilled_from_the_origin_ticket(migrator: Migrator):
    """0045가 만든 슬라이스는 티켓의 작성자를 물려받아야 한다.

    0046 시점에 Ticket 테이블은 아직 살아 있으므로(파괴적 제거는 마지막
    마이그레이션), number로 짝지어 백필할 수 있다."""
    old = migrator.apply_initial_migration(BEFORE_0046)
    Org = old.apps.get_model("core", "Org")
    User = old.apps.get_model("core", "User")
    OrgMember = old.apps.get_model("core", "OrgMember")
    Ticket = old.apps.get_model("core", "Ticket")
    Slice = old.apps.get_model("core", "Slice")

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    user = User.objects.create(email="a@b.com")
    member = OrgMember.objects.create(user=user, org=org, role="owner")
    Ticket.objects.create(
        org=org, title="캡처", body="", status="open", number=7, rank="m",
        created_by=member,
    )
    # 0045가 이미 적용된 상태에서 시작하므로, 0045가 만들었을 슬라이스를 직접 재현한다.
    Slice.objects.create(org=org, title="캡처", spec="", rank="m", number=7)

    new = migrator.apply_tested_migration(AFTER_0046)
    NewSlice = new.apps.get_model("core", "Slice")
    s = NewSlice.objects.get(number=7)
    assert s.created_by_id == member.id


@pytest.mark.django_db
def test_a_null_number_ticket_does_not_stamp_every_null_number_slice(migrator: Migrator):
    """백필의 짝짓기 키는 number인데, Ticket.number와 Slice.number 둘 다
    null=True이고 유니크 제약이 NULL을 배제하는 부분 인덱스다.

    Django ORM에서 number=None 필터는 `number IS NULL`로 번역되므로, number가
    NULL이면서 created_by가 있는 티켓 하나가 그 org의 number가 NULL인 슬라이스
    '전부'에 자기 작성자를 찍는다 — 아무 관계도 없는 행에.

    0046은 양쪽 다 NULL을 제외해야 한다."""
    old = migrator.apply_initial_migration(BEFORE_0046)
    Org = old.apps.get_model("core", "Org")
    User = old.apps.get_model("core", "User")
    OrgMember = old.apps.get_model("core", "OrgMember")
    Ticket = old.apps.get_model("core", "Ticket")
    Slice = old.apps.get_model("core", "Slice")

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    user = User.objects.create(email="a@b.com")
    member = OrgMember.objects.create(user=user, org=org, role="owner")
    # number가 NULL인 티켓 — 짝지을 슬라이스가 없다.
    Ticket.objects.create(
        org=org, title="번호 없는 캡처", body="", status="open", number=None, rank="m",
        created_by=member,
    )
    # number가 NULL인, 전혀 무관한 슬라이스 둘.
    a = Slice.objects.create(org=org, title="무관 A", spec="", rank="a", number=None)
    b = Slice.objects.create(org=org, title="무관 B", spec="", rank="b", number=None)

    new = migrator.apply_tested_migration(AFTER_0046)
    NewSlice = new.apps.get_model("core", "Slice")
    assert NewSlice.objects.get(pk=a.pk).created_by_id is None
    assert NewSlice.objects.get(pk=b.pk).created_by_id is None


@pytest.mark.django_db
def test_created_by_stays_null_when_the_ticket_never_had_one(migrator: Migrator):
    old = migrator.apply_initial_migration(BEFORE_0046)
    Org = old.apps.get_model("core", "Org")
    Ticket = old.apps.get_model("core", "Ticket")
    Slice = old.apps.get_model("core", "Slice")

    org = Org.objects.create(name="O", slug="o", key="O", next_slice_number=9)
    Ticket.objects.create(org=org, title="캡처", body="", status="open", number=7, rank="m")
    Slice.objects.create(org=org, title="캡처", spec="", rank="m", number=7)

    new = migrator.apply_tested_migration(AFTER_0046)
    NewSlice = new.apps.get_model("core", "Slice")
    assert NewSlice.objects.get(number=7).created_by_id is None


@pytest.mark.django_db
def test_0046_backward_touches_no_rows(django_assert_num_queries):
    """되감기는 정말로 아무것도 하지 않아야 한다 — 필드가 사라지면 값도 사라지고,
    원본(Ticket)이 그대로 남아 있어 정보 손실이 없기 때문이다.

    예전 단언은 `assert mod.backward(None, None) is None` 이었는데, 이것은
    return 문이 없는 '모든' 함수에 대해 참이다. 파괴적인 본문
    (`Slice.objects.update(created_by=None)` 같은 것)을 넣어도 똑같이 통과한다.
    쿼리 수를 세면 그 구분이 생긴다: 아무것도 안 하는 함수만 0 쿼리다.

    apps는 전역 레지스트리를 넘긴다 — apps.get_model()을 쓰는 본문이라면
    그대로 동작하고, 실제로 DB를 만지면 쿼리로 드러난다."""
    from django.apps import apps as global_apps

    mod = importlib.import_module("tuckit.core.migrations.0046_schema_repair")
    with django_assert_num_queries(0):
        assert mod.backward(global_apps, None) is None

    # 그리고 RunPython에 실제로 물려 있어야 한다 (test_backward_refuses_to_run과 같은 이유).
    run_pythons = [op for op in mod.Migration.operations if isinstance(op, migrations.RunPython)]
    assert run_pythons and all(op.reverse_code is mod.backward for op in run_pythons)
