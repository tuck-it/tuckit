import hashlib
import hmac

import pytest

from tuckit.integrations.slack.signing import SlackSignatureError, verify_signature

SECRET = "8f742231b10e8888abcd99yyyzzz85a5"
BODY = b"token=xyz&team_id=T111"


def sign(timestamp: str, body: bytes = BODY, secret: str = SECRET) -> str:
    base = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def test_accepts_a_genuine_signature():
    verify_signature(
        signing_secret=SECRET, timestamp="1700000000", raw_body=BODY,
        signature=sign("1700000000"), now=1700000000.0,
    )


def test_rejects_a_tampered_body():
    with pytest.raises(SlackSignatureError):
        verify_signature(
            signing_secret=SECRET, timestamp="1700000000", raw_body=b"token=xyz&team_id=T999",
            signature=sign("1700000000"), now=1700000000.0,
        )


def test_rejects_a_replay_older_than_five_minutes():
    with pytest.raises(SlackSignatureError):
        verify_signature(
            signing_secret=SECRET, timestamp="1700000000", raw_body=BODY,
            signature=sign("1700000000"), now=1700000000.0 + 301,
        )


def test_rejects_a_malformed_timestamp():
    with pytest.raises(SlackSignatureError):
        verify_signature(
            signing_secret=SECRET, timestamp="not-a-number", raw_body=BODY,
            signature="v0=whatever", now=1700000000.0,
        )
