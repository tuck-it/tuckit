import httpx
from django.conf import settings

BASE_URL = "https://slack.com/api"
DEFAULT_TIMEOUT = 10.0


class SlackApiError(Exception):
    """Slack answered, and said no.

    Slack returns HTTP 200 with {"ok": false, "error": "..."} for application
    errors, so a caller that only checks the status code discards every error
    Slack ever reports. Nothing here swallows.
    """


class SlackClient:
    def __init__(self, bot_token: str, timeout: float = DEFAULT_TIMEOUT):
        self._token = bot_token
        self._http = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def _call(self, method: str, **payload) -> dict:
        response = self._http.post(
            f"/{method}",
            json={k: v for k, v in payload.items() if v is not None},
            headers={"Authorization": f"Bearer {self._token}"},
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise SlackApiError(f"{method}: {data.get('error', 'unknown')}")
        return data

    def post_message(self, *, channel: str, text: str, thread_ts: str | None = None,
                     blocks: list | None = None) -> str:
        data = self._call("chat.postMessage", channel=channel, text=text,
                          thread_ts=thread_ts, blocks=blocks)
        return data["ts"]

    def update_message(self, *, channel: str, ts: str, text: str,
                       blocks: list | None = None) -> None:
        self._call("chat.update", channel=channel, ts=ts, text=text, blocks=blocks)

    def post_ephemeral(self, *, channel: str, user: str, text: str,
                       thread_ts: str | None = None, blocks: list | None = None) -> None:
        self._call("chat.postEphemeral", channel=channel, user=user, text=text,
                   thread_ts=thread_ts, blocks=blocks)

    def conversations_replies(self, *, channel: str, thread_ts: str,
                              limit: int = 100) -> list[dict]:
        data = self._call("conversations.replies", channel=channel, ts=thread_ts, limit=limit)
        return data.get("messages", [])

    def chat_unfurl(self, *, channel: str, ts: str, unfurls: dict) -> None:
        self._call("chat.unfurl", channel=channel, ts=ts, unfurls=unfurls)

    def users_info(self, *, user_id: str) -> dict:
        # users:read only. We never request users:read.email, so nothing here
        # can return one — see the slice constraints.
        return self._call("users.info", user=user_id)["user"]


def exchange_oauth_code(*, code: str, redirect_uri: str) -> dict:
    """Trade an install code for a bot token. Unauthenticated call, so it does
    not go through SlackClient.
    """
    response = httpx.post(
        f"{BASE_URL}/oauth.v2.access",
        data={
            "client_id": settings.SLACK_CLIENT_ID,
            "client_secret": settings.SLACK_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise SlackApiError(f"oauth.v2.access: {data.get('error', 'unknown')}")
    return data
