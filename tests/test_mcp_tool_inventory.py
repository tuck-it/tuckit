import pytest


@pytest.mark.asyncio
async def test_registered_tools_are_exactly_the_fourteen():
    from tuckit.core.mcp.server import mcp

    tools = {t.name for t in await mcp.list_tools()}
    expected = {
        "get_project_state", "list_areas", "create_area",
        "list_slices", "get_slice", "create_slice", "update_slice", "add_note",
        "list_plans", "create_plan", "update_plan",
        "list_bites", "add_bites", "update_bite",
    }
    assert tools == expected

    removed = {"list_tags", "set_slice_status", "reorder_slice",
               "set_bite_status", "reorder_bite", "create_bite", "whoami"}
    assert tools.isdisjoint(removed)
