import importlib

import pytest

from tests.migration_utils import at, forward, leave_migrated


@pytest.mark.django_db(transaction=True)
def test_backfill_creates_org_and_migrates_membership():
    # Replay forward to just-before the backfill (see tests/migration_utils.py:
    # rolling backward is no longer possible past 0045).
    old = at(("core", "0002_org_alter_workspace_slug_invitation_workspace_org_and_more"))

    User = old.get_model("core", "User")
    Workspace = old.get_model("core", "Workspace")
    Membership = old.get_model("core", "Membership")

    u = User.objects.create(email="a@b.com")
    ws = Workspace.objects.create(name="Legacy", slug="legacy")
    Membership.objects.create(user=u, workspace=ws, role="owner")

    # Apply the backfill.
    new = forward(("core", "0003_backfill_orgs"))

    Workspace = new.get_model("core", "Workspace")
    OrgMember = new.get_model("core", "OrgMember")
    ws = Workspace.objects.get(slug="legacy")
    assert ws.org is not None
    assert OrgMember.objects.filter(user__email="a@b.com", org=ws.org, role="owner").exists()

    # Leave the DB migrated forward for the rest of the suite.
    leave_migrated()


@pytest.mark.django_db(transaction=True)
def test_dismissed_workspace_backfilled_completed():
    """Workspace no longer exists in the current app registry (deleted in
    Task 12), so this exercises the frozen 0012 migration function against
    the historical model state as of that migration, the same way
    test_backfill_creates_org_and_migrates_membership does above."""
    historical_apps = at(("core", "0012_workspace_onboarding_completed"))

    Org = historical_apps.get_model("core", "Org")
    Workspace = historical_apps.get_model("core", "Workspace")

    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(
        org=org, name="P", slug="p",
        onboarding_dismissed=True, onboarding_completed=False,
    )

    mod = importlib.import_module(
        "tuckit.core.migrations.0012_workspace_onboarding_completed"
    )
    mod.backfill_completed(historical_apps, None)
    ws.refresh_from_db()
    assert ws.onboarding_completed is True

    # Leave the DB migrated forward for the rest of the suite.
    leave_migrated()
