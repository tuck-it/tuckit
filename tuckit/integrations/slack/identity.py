from django.core import signing

from tuckit.integrations.slack.models import SlackIdentity

CONNECT_STATE_SALT = "slack-connect"
CONNECT_STATE_MAX_AGE_SECONDS = 900


def resolve_member(install, slack_user_id: str):
    """The person behind a Slack user, or None. This is the access gate.

    member__ended_at__isnull=True is load-bearing and cannot be dropped. A
    membership ends by stamping ended_at rather than by deletion, and
    OrgMember.Meta.base_manager_name = "all_objects" makes forward FK access
    resolve ended memberships deliberately, so without this filter someone who
    left the org keeps writing through Slack forever. Slice 232 is the same
    defect on the MCP side.

    There is also deliberately no fallback that looks the person up by email:
    Slack's email is workspace-owned and unverified, so trusting it would let a
    hostile workspace admin write to the board as somebody else.
    """
    identity = (
        SlackIdentity.objects
        .filter(
            install=install,
            slack_user_id=slack_user_id,
            member__ended_at__isnull=True,
        )
        .select_related("member", "member__user")
        .first()
    )
    return identity.member if identity else None


def connect_state(install, slack_user_id: str) -> str:
    return signing.dumps(
        {"install_id": install.id, "slack_user_id": slack_user_id},
        salt=CONNECT_STATE_SALT,
    )


def connect_blocks(connect_url: str) -> list:
    """The ephemeral prompt. One button, at the moment of the failed mention --
    nobody should have to go and discover a slash command."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "I do not know who you are in tuckit yet, so I have not "
                    "written anything. Connect your account and mention me again."
                ),
            },
        },
        {
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Connect tuckit account"},
                "url": connect_url,
                "style": "primary",
            }],
        },
    ]
