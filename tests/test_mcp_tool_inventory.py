import pytest

# Eleven tools, one vocabulary: areas, slices, bites, notes. Every tool an
# agent can call is on this list, and the list is the product's agent-facing
# API — it grows only on purpose.
EXPECTED = {
    "get_project_state", "list_areas", "create_area",
    "list_slices", "get_slice", "create_slice", "update_slice", "add_note",
    "list_bites", "add_bites", "update_bite",
}

# Removed for good, with the reason each one cannot come back:
#
# - the seven ticket tools: Ticket is gone as a concept. promote_ticket was
#   the last irreversible operation in the product, and reopen_ticket refused
#   a promoted ticket — a capture that had been promoted could never go back.
#   An area-less Slice is the Inbox now, and filing is reversible in both
#   directions (update_slice(area_id=...) / update_slice(area_id="")).
# - the three plan tools: bites hang off the slice, and a slice's own `spec`
#   and `constraints` hold what a plan used to.
#
# Deliberately NOT kept as aliases. A `create_ticket` shim would keep "ticket"
# in the one vocabulary an agent reads, which is the whole thing this release
# removes.
REMOVED = {
    "list_tickets", "create_ticket", "get_ticket", "update_ticket",
    "promote_ticket", "absorb_ticket", "release_ticket",
    "list_plans", "create_plan", "update_plan",
    # retired earlier, still must not reappear
    "list_tags", "set_slice_status", "reorder_slice",
    "set_bite_status", "reorder_bite", "create_bite", "whoami",
}


@pytest.mark.asyncio
async def test_registered_tools_are_exactly_the_eleven():
    from tuckit.core.mcp.server import mcp

    tools = {t.name for t in await mcp.list_tools()}
    assert tools == EXPECTED
    assert len(tools) == 11
    assert tools.isdisjoint(REMOVED)


@pytest.mark.asyncio
async def test_no_removed_tool_survives_as_a_module_level_function():
    """The registry is the contract, but a leftover module-level coroutine is
    how a tool comes back: re-adding one `@mcp.tool()` above an existing
    function is a one-line change. Assert the functions themselves are gone."""
    from tuckit.core.mcp import server

    for gone in REMOVED:
        assert not hasattr(server, gone), f"{gone} is still defined in mcp/server.py"


@pytest.mark.asyncio
async def test_the_agent_facing_surface_never_says_ticket_or_plan():
    """Docstrings are the only documentation an agent ever reads. A tool
    description that still explains tickets or plans teaches a vocabulary the
    product no longer has, which is worse than saying nothing."""
    from tuckit.core.mcp.server import mcp

    import re

    for tool in await mcp.list_tools():
        text = f"{tool.name} {tool.description or ''}".lower()
        for word in ("ticket", "promote", "plan"):
            assert not re.search(rf"\b{word}", text), \
                f"{tool.name} still talks about {word!r}"


@pytest.mark.asyncio
async def test_every_tool_carries_a_description():
    """An undocumented tool is an unusable one — the agent has nothing else."""
    from tuckit.core.mcp.server import mcp

    for tool in await mcp.list_tools():
        assert (tool.description or "").strip(), f"{tool.name} has no docstring"


@pytest.mark.asyncio
async def test_every_registered_tool_goes_through_the_rate_limiter():
    """The limiter lives inside require_org / require_caller. A tool that
    resolved auth some other way would route around it silently, so assert the
    source of every registered tool calls one of the two. The other half of
    this invariant -- that those two actually enforce -- is asserted in
    tests/test_mcp_ratelimit.py.
    """
    import inspect

    from tuckit.core.mcp import server

    for name in EXPECTED:
        src = inspect.getsource(getattr(server, name))
        assert "require_org(ctx)" in src or "require_caller(ctx)" in src, (
            f"{name} does not resolve auth through require_org/require_caller, "
            f"so it never reaches the rate limiter"
        )
