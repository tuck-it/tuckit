import pytest

from tuckit.core.management.commands.bootstrap import ensure_bootstrap


@pytest.mark.django_db
def test_workspace_shipped_board_defaults():
    ws, _ = ensure_bootstrap()
    assert ws.shipped_board_mode == "count"
    assert ws.shipped_board_limit == 8


def test_stat_snapshot_unique_per_workspace_per_day(db):
    from datetime import date
    from django.db import IntegrityError
    from tuckit.core.models import Org, Workspace, WorkspaceStatSnapshot
    org = Org.objects.create(name="Acme", slug="acme")
    ws = Workspace.objects.create(org=org, name="P", slug="p")
    d = date(2026, 7, 14)
    WorkspaceStatSnapshot.objects.create(workspace=ws, date=d, building_ct=3)
    with pytest.raises(IntegrityError):
        WorkspaceStatSnapshot.objects.create(workspace=ws, date=d, building_ct=9)
