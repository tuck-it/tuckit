"""Slack block-kit rendering for the app_mention result card.

Kept free of any tuckit or Slack API imports on purpose: everything here is
pure formatting, so it can be tested without a database or a network call.
"""
PLACEHOLDER_TEXT = "Reading this thread…"


def placeholder_text(message_count: int) -> str:
    noun = "message" if message_count == 1 else "messages"
    return f"Reading this thread ({message_count} {noun})…"


def result_blocks(*, results, actor_name: str, message_count: int, board_url: str) -> list:
    """One card listing every outcome.

    The card names who caused it, because for the people in the thread without
    tuckit accounts this is the only notice their words reached the board.
    """
    lines = []
    for result in results:
        if result.ok:
            label = f"<{board_url}|{result.ref}> {result.label}" if result.ref else result.label
            lines.append(f"• {label}")
        else:
            lines.append(f"• _not filed_ — {result.error}")
    if not lines:
        lines = ["• _nothing to file from this thread_"]

    noun = "message" if message_count == 1 else "messages"
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        {"type": "context", "elements": [{
            "type": "mrkdwn",
            "text": f"Filed by {actor_name} from {message_count} {noun} in this thread.",
        }]},
    ]


def failure_blocks(message: str) -> list:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": f":warning: {message}"}}]


def unfurl_block(slice_) -> dict:
    """The Slack chat.unfurl payload for one tuckit link.

    Imports refs/slices services locally, not at module scope, so this module
    stays free of tuckit imports at import time (see the module docstring) --
    it only needs them once a real slice is being rendered.
    """
    from tuckit.core.services.refs import slice_ref
    from tuckit.core.services.slices import stage_of

    area = slice_.area.name if slice_.area else "Inbox"
    return {
        "blocks": [
            {"type": "section", "text": {
                "type": "mrkdwn",
                "text": f"*{slice_ref(slice_)}  {slice_.title}*",
            }},
            {"type": "context", "elements": [{
                "type": "mrkdwn", "text": f"{area}  ·  {stage_of(slice_)}",
            }]},
        ],
    }
