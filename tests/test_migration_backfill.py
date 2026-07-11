import pytest
from django.db.migrations.executor import MigrationExecutor
from django.db import connection


@pytest.mark.django_db(transaction=True)
def test_backfill_creates_org_and_migrates_membership():
    executor = MigrationExecutor(connection)
    # Roll back to just-before the backfill.
    executor.migrate([("core", "0002_org_alter_workspace_slug_invitation_workspace_org_and_more")])
    executor.loader.build_graph()
    old = executor.loader.project_state(
        [("core", "0002_org_alter_workspace_slug_invitation_workspace_org_and_more")]
    ).apps

    User = old.get_model("core", "User")
    Workspace = old.get_model("core", "Workspace")
    Membership = old.get_model("core", "Membership")

    u = User.objects.create(username="a@b.com", email="a@b.com")
    ws = Workspace.objects.create(name="Legacy", slug="legacy")
    Membership.objects.create(user=u, workspace=ws, role="owner")

    # Apply the backfill.
    executor = MigrationExecutor(connection)
    executor.migrate([("core", "0003_backfill_orgs")])
    new = executor.loader.project_state([("core", "0003_backfill_orgs")]).apps

    Workspace = new.get_model("core", "Workspace")
    OrgMember = new.get_model("core", "OrgMember")
    ws = Workspace.objects.get(slug="legacy")
    assert ws.org is not None
    assert OrgMember.objects.filter(user__email="a@b.com", org=ws.org, role="owner").exists()

    # Leave the DB migrated forward for the rest of the suite.
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
