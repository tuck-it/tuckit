"""What the result card actually says.

Everything the Slack integration produces that a person ever sees comes out of
`cards`, and none of it was pinned: making `result_blocks` return `[]` and
`placeholder_text` return `""` left 90 of the 91 Slack tests passing, because
every one of them counted messages rather than reading them. These tests read
the rendered text.

No database and no network: `cards` is pure formatting and `Applied` is a
frozen dataclass, so this file needs neither.
"""
from tuckit.integrations.slack import cards
from tuckit.integrations.slack.apply import Applied


def text_of(blocks) -> str:
    """Every string a Slack block-kit payload would put on screen, joined.

    Asserting against this rather than a fixed block index means a card that
    re-arranges its sections still passes, while a card that drops the content
    fails.
    """
    out = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "text" and isinstance(value, str):
                    out.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(blocks)
    return "\n".join(out)


SLICE = Applied(ok=True, ref="TP-300", label="The login banner",
                url="https://tuckit.example/acme/slices/7/")
AREA = Applied(ok=True, ref="", label="Billing")
FAILED = Applied(ok=False, error="no slice TP-999")


def test_the_card_names_every_created_ref_and_what_it_was():
    body = text_of(cards.result_blocks(
        results=[SLICE, AREA], actor_name="Dana Lee", message_count=4,
    ))
    assert "TP-300" in body
    assert "The login banner" in body
    assert "Billing" in body


def test_a_ref_links_to_its_own_slice_not_the_board():
    body = text_of(cards.result_blocks(
        results=[SLICE], actor_name="Dana Lee", message_count=4,
    ))
    # Slack's link syntax is <url|label>. The URL must be the slice's own
    # deep link: linking every ref to the board root sent a reader who
    # clicked TP-300 to a board and left them to find TP-300 themselves.
    assert "<https://tuckit.example/acme/slices/7/|TP-300>" in body


def test_the_card_names_the_actor_and_how_many_messages_were_read():
    body = text_of(cards.result_blocks(
        results=[SLICE], actor_name="Dana Lee", message_count=4,
    ))
    assert "Dana Lee" in body
    assert "4 messages" in body


def test_one_message_is_not_called_messages():
    body = text_of(cards.result_blocks(
        results=[SLICE], actor_name="Dana Lee", message_count=1,
    ))
    assert "1 message" in body
    assert "1 messages" not in body


def test_a_failed_result_shows_its_error_text():
    body = text_of(cards.result_blocks(
        results=[FAILED], actor_name="Dana Lee", message_count=2,
    ))
    assert "no slice TP-999" in body


def test_a_mixed_card_shows_both_the_success_and_the_failure():
    """The failure must not be swallowed by the success sitting next to it:
    a card that silently listed only what worked would report a partial run
    as a clean one."""
    body = text_of(cards.result_blocks(
        results=[SLICE, FAILED], actor_name="Dana Lee", message_count=2,
    ))
    assert "TP-300" in body
    assert "no slice TP-999" in body


def test_a_card_with_no_results_says_so_rather_than_going_blank():
    body = text_of(cards.result_blocks(
        results=[], actor_name="Dana Lee", message_count=3,
    ))
    assert "nothing to file" in body
    assert "Dana Lee" in body


def test_the_placeholder_names_the_number_of_messages_being_read():
    assert "3 messages" in cards.placeholder_text(3)
    assert "1 message" in cards.placeholder_text(1)
    assert "1 messages" not in cards.placeholder_text(1)


def test_a_failure_card_carries_the_sentence_it_was_given():
    body = text_of(cards.failure_blocks("This deployment has no interpretation configured"))
    assert "This deployment has no interpretation configured" in body
