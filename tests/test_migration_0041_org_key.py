"""0041/0042 마이그레이션 — 기존 org의 key backfill과 활동 로그 ref 재작성.

눈으로 확인하는 대신 테스트를 거는 이유: backfill이 틀리면 균일하게 틀리고,
그 결과 배포된 모든 org의 ref 접두사가 한꺼번에 어긋난다.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = ("core", "0039_alter_activityevent_verb_and_more")
AFTER = ("core", "0042_activity_ref_format")


def _at(state):
    executor = MigrationExecutor(connection)
    executor.migrate([state])
    executor.loader.build_graph()
    return executor.loader.project_state([state]).apps


def _forward():
    executor = MigrationExecutor(connection)
    executor.migrate([AFTER])
    return executor.loader.project_state([AFTER]).apps


def _leave_migrated():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_backfills_keys_and_rewrites_activity_refs():
    old = _at(BEFORE)
    Org = old.get_model("core", "Org")
    ActivityEvent = old.get_model("core", "ActivityEvent")

    a = Org.objects.create(name="A", slug="tuckit-projects")
    b = Org.objects.create(name="B", slug="tuckit-plugins")
    ActivityEvent.objects.create(
        org=a, actor="agent", verb="promoted", target_type="ticket",
        target_id=1, target_label="t", to_value="tuckit-projects-47",
    )
    # Another org's ref shape must not be touched by A's pattern.
    ActivityEvent.objects.create(
        org=b, actor="agent", verb="promoted", target_type="ticket",
        target_id=2, target_label="t", to_value="tuckit-plugins-3",
    )
    # A non-ref to_value (a plain status) must survive untouched.
    ActivityEvent.objects.create(
        org=a, actor="human", verb="status_changed", target_type="slice",
        target_id=3, target_label="s", to_value="shipped",
    )
    # A ref-SHAPED to_value on a non-'promoted' verb must also survive: only
    # promote_ticket/absorb_ticket ever write a real ref into to_value. This
    # is what an Area named "<org-slug>-<digits>" would produce on a 'moved'
    # event — absurd, but the pattern alone can't tell it apart from a real
    # ref without the verb filter.
    ActivityEvent.objects.create(
        org=a, actor="human", verb="moved", target_type="slice",
        target_id=4, target_label="s", to_value="tuckit-projects-99",
    )

    new = _forward()
    Org = new.get_model("core", "Org")
    ActivityEvent = new.get_model("core", "ActivityEvent")

    assert Org.objects.get(slug="tuckit-projects").key == "TP"
    assert Org.objects.get(slug="tuckit-plugins").key == "TP2"

    values = set(ActivityEvent.objects.values_list("to_value", flat=True))
    assert values == {"TP-47", "TP2-3", "shipped", "tuckit-projects-99"}

    _leave_migrated()
