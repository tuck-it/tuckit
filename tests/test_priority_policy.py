import pytest

from asgiref.sync import sync_to_async

from tuckit.core.mcp.server import append_priority_policy
from tuckit.core.models import Org
from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.tokens import generate_token
from tests.test_mcp_tools_state import make_ctx


@sync_to_async
def _seed(policy=""):
    org = Org.objects.create(name="Acme", slug="acme", priority_policy=policy)
    _, raw = generate_token(org, "t")
    return org, raw


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_appending_keeps_everything_that_was_there():
    """The policy is written a line at a time, over weeks, out of corrections a
    person made to a wrong classification. One call must never be able to cost
    them that."""
    org, raw = await _seed("1 = money in hand this week.")

    result = await append_priority_policy(
        make_ctx(raw), "With zero customers, outreach beats most bugs.",
    )

    assert "1 = money in hand this week." in result["priority_policy"]
    assert "outreach beats most bugs" in result["priority_policy"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_empty_line_is_refused():
    """Whitespace would append a blank row and look like it worked."""
    _org, raw = await _seed("1 = money.")

    with pytest.raises(InvalidValue):
        await append_priority_policy(make_ctx(raw), "   ")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_refused_line_does_not_touch_the_policy():
    """Refusing is only half of it: a guard that raises AFTER writing would
    still have cost the text it was protecting."""
    org, raw = await _seed("1 = money.")

    with pytest.raises(InvalidValue):
        await append_priority_policy(make_ctx(raw), "  \n  ")

    await _assert_policy_is(org, "1 = money.")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_first_line_needs_no_leading_blank():
    _org, raw = await _seed("")

    result = await append_priority_policy(make_ctx(raw), "1 = money.")

    assert result["priority_policy"] == "1 = money."


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_appending_twice_keeps_both_lines_in_order():
    """Weeks of corrections accumulate through this path, so order is part of
    the artifact -- a policy read back scrambled is not the one anyone wrote."""
    _org, raw = await _seed("1 = money.")

    await append_priority_policy(make_ctx(raw), "2 = a promised date.")
    result = await append_priority_policy(make_ctx(raw), "3 = everything else.")

    assert result["priority_policy"] == (
        "1 = money.\n2 = a promised date.\n3 = everything else."
    )


def test_no_mcp_tool_can_replace_or_clear_the_policy():
    """append-only is a claim about the tool surface, so the tool surface is what
    gets asserted. Without this the guarantee is a comment.

    Underscore names are excluded on purpose: this module imports its services
    under a leading underscore (`_append_priority_policy`, matching
    `_create_slice` and the rest of the file), and those are not tools. What is
    being asserted is what an AGENT can call.
    """
    import inspect

    from tuckit.core.mcp import server

    tools = [
        name for name in dir(server)
        if not name.startswith("_")
        and "policy" in name
        and callable(getattr(server, name))
    ]

    assert tools == ["append_priority_policy"]
    assert "priority_policy" not in inspect.signature(server.update_slice).parameters
    assert "priority_policy" not in inspect.signature(server.create_slice).parameters


@sync_to_async
def _assert_policy_is(org, expected):
    org.refresh_from_db()
    assert org.priority_policy == expected
