"""Regression test for the Critical finding on 0022_delete_workspace: legacy
orgs that had 2+ Workspaces seeded duplicate Area(slug="triage") rows, reused
Tag names, and snapshotted the same day across their workspaces. Once
`workspace` stops being a tenant column and org-scoped uniqueness constraints
are added, those pre-existing collisions must be deduplicated first or the
migration aborts with IntegrityError on any real database with that shape.

This mirrors the MigrationExecutor pattern in test_migration_backfill.py:
migrate to just-before the fix, seed the exact colliding shape via historical
models, migrate forward, and assert it applies cleanly with data preserved
(Areas/Tags) or safely collapsed (derived snapshots).
"""

import datetime

import pytest

from tests.migration_utils import at, forward, leave_migrated


@pytest.mark.django_db(transaction=True)
def test_dedup_resolves_legacy_multi_workspace_collisions():
    old = at(("core", "0021_workspace_fk_nullable"))

    Org = old.get_model("core", "Org")
    Workspace = old.get_model("core", "Workspace")
    Area = old.get_model("core", "Area")
    Tag = old.get_model("core", "Tag")
    Snapshot = old.get_model("core", "WorkspaceStatSnapshot")

    org = Org.objects.create(name="Acme", slug="acme")
    ws1 = Workspace.objects.create(org=org, name="Team One", slug="team-one")
    ws2 = Workspace.objects.create(org=org, name="Team Two", slug="team-two")

    same_day = datetime.date(2026, 7, 1)

    for i, ws in enumerate((ws1, ws2), start=1):
        Area.objects.create(
            org=org, workspace=ws, name="Triage", slug="triage", rank=f"a{i}",
        )
        Tag.objects.create(org=org, workspace=ws, name="urgent")
        Snapshot.objects.create(org=org, workspace=ws, date=same_day)

    # Sanity: the pre-existing rows really do collide under (org, slug) /
    # (org, name) / (org, date) -- this is the shape that broke 0022.
    assert Area.objects.filter(org=org, slug="triage").count() == 2
    assert Tag.objects.filter(org=org, name="urgent").count() == 2
    assert Snapshot.objects.filter(org=org, date=same_day).count() == 2

    # Apply the fixed migration. Must NOT raise IntegrityError.
    new = forward(("core", "0022_delete_workspace"))

    NewArea = new.get_model("core", "Area")
    NewTag = new.get_model("core", "Tag")
    NewSnapshot = new.get_model("core", "OrgStatSnapshot")

    areas = list(NewArea.objects.filter(org_id=org.id).order_by("id"))
    assert len(areas) == 2, "dedup must not delete Areas -- slices hang off them"
    assert {a.slug for a in areas} == {"triage", "triage-2"}

    tags = list(NewTag.objects.filter(org_id=org.id).order_by("id"))
    assert len(tags) == 2, "dedup must not delete Tags -- may be slice-referenced"
    assert {t.name for t in tags} == {"urgent", "urgent (2)"}

    snapshots = list(NewSnapshot.objects.filter(org_id=org.id, date=same_day))
    assert len(snapshots) == 1, "derived snapshots collapse to exactly one row per (org, date)"

    # Leave the DB migrated forward for the rest of the suite.
    leave_migrated()
