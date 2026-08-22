from dataclasses import dataclass

import anthropic
from django.conf import settings

from tuckit.integrations.slack.config import interpretation_is_configured

MODEL = "claude-opus-5"
MAX_INTENTS = 5
MAX_TOKENS = 4096


class InterpretationUnavailable(Exception):
    """This deployment has no model key. Say so; do not pretend to understand."""


class TooManyIntents(Exception):
    """The thread looked like more than MAX_INTENTS things.

    Nothing is written in this case. A mention that silently files eleven
    slices is worse than one that files none.
    """


@dataclass(frozen=True)
class Intent:
    tool: str
    args: dict


SYSTEM = """You read a Slack thread and decide what belongs on a tuckit board.

tuckit has exactly one unit of work, the Slice: a title, a spec (what we are
building and why), and an optional Area. A Slice that has no Area sits in the
Inbox, which is a normal place for it to be, not a failure.

Rules:
- Call one tool per distinct piece of work in the thread. Several is normal.
- If something in the thread is already on the board below, call add_note with
  its ref instead of creating a near-duplicate.
- Pick an area only when the thread makes it obvious. Otherwise pass "" and it
  goes to the Inbox, which is easy to file later.
- If the thread is not about work at all, or you cannot tell what is being
  asked, call ask_clarification and nothing will be written.
- Write the spec so someone who was not in the thread can act on it.
"""


def build_tools(area_slugs: list[str]) -> list[dict]:
    # "" is a real choice, not a missing value: strict mode requires every
    # property to be present, so optionality is expressed in the enum.
    area = {"type": "string", "enum": [*area_slugs, ""],
            "description": "Area slug, or empty string for the Inbox"}

    def tool(name, description, properties):
        return {
            "name": name,
            "description": description,
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        }

    return [
        tool("create_slice", "File a new piece of work.", {
            "title": {"type": "string"},
            "spec": {"type": "string", "description": "What and why, for someone who was not there"},
            "area": area,
        }),
        tool("create_area", "Create a new long-lived area of responsibility.", {
            "name": {"type": "string"},
            "description": {"type": "string"},
        }),
        tool("add_note", "Append to an existing slice named by its ref.", {
            "ref": {"type": "string", "description": "A ref like TP-214. Never a bare number."},
            "body": {"type": "string"},
        }),
        tool("ask_clarification", "Write nothing and ask the person what they meant.", {
            "question": {"type": "string"},
        }),
    ]


def _board_digest(open_slices: list[tuple[str, str]]) -> str:
    if not open_slices:
        return "The board has no open slices yet."
    lines = "\n".join(f"- {ref}: {title}" for ref, title in open_slices)
    return f"Open slices already on the board:\n{lines}"


def _call_model(*, system: list, tools: list, messages: list):
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        tools=tools,
        # This is mechanical extraction over a small vocabulary, not a problem
        # that rewards deliberation.
        output_config={"effort": "low"},
        messages=messages,
    )


def interpret(*, messages: list[str], area_slugs: list[str],
              open_slices: list[tuple[str, str]]) -> list[Intent]:
    if not interpretation_is_configured():
        raise InterpretationUnavailable("no ANTHROPIC_API_KEY configured")

    # The instructions and the board digest are identical between requests, so
    # they sit behind the cache breakpoint and the thread text goes after it.
    system = [
        {"type": "text", "text": SYSTEM},
        {"type": "text", "text": _board_digest(open_slices),
         "cache_control": {"type": "ephemeral"}},
    ]
    thread = "\n".join(messages)
    response = _call_model(
        system=system,
        tools=build_tools(area_slugs),
        messages=[{"role": "user", "content": f"Slack thread:\n\n{thread}"}],
    )

    intents = [
        Intent(tool=block.name, args=dict(block.input))
        for block in response.content
        if getattr(block, "type", "") == "tool_use"
    ]
    if len(intents) > MAX_INTENTS:
        raise TooManyIntents(f"{len(intents)} intents exceeds the cap of {MAX_INTENTS}")
    return intents
