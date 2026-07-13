import pytest

from tuckit.core.management.commands.bootstrap import ensure_bootstrap


@pytest.mark.django_db
def test_workspace_shipped_board_defaults():
    ws, _ = ensure_bootstrap()
    assert ws.shipped_board_mode == "count"
    assert ws.shipped_board_limit == 8
