"""A refusal the server explains, and the screen reduces to "went wrong".

base.html surfaces a failed request's plain-text body as a toast, but only up
to a length ceiling — a crude proxy for "is this prose or an HTML error page".
The ceiling was 200 characters. A deployment that closes writes answers with a
paragraph (what happened, that nothing was deleted, what to do), which is
longer, so the one refusal the product takes care to explain was the only one
that came back as "Something went wrong (402). Nothing was saved."

Nothing went wrong. Found by clicking Create on a read-only workspace; no
endpoint test could have seen it, because the endpoint was already returning
the right sentence.
"""
import pathlib
import re

import pytest
from django.test import override_settings

from tuckit.core.entitlements import Entitlements

REASON = (
    "Your 14-day trial ended on 19 Aug 2026. tuckit is read-only until you "
    "subscribe: https://example.test/cloud/upgrade Nothing has been deleted — "
    "everything you and your agents wrote is still here, and you can export "
    "all of it at any time."
)


def _blocked(org):
    return Entitlements(writes_blocked_reason=REASON)


BLOCK = override_settings(
    TUCKIT_ENTITLEMENTS_HOOK="tests.web.test_blocked_write_reason_reaches_the_screen._blocked"
)


def _toast_ceiling():
    """The number base.html actually uses, read from base.html."""
    src = pathlib.Path("tuckit/web/templates/web/base.html").read_text()
    m = re.search(r"body\.length < (\d+)", src)
    assert m, "the plain-text guard in base.html moved or changed shape"
    return int(m.group(1))


@BLOCK
@pytest.mark.django_db
def test_the_refusal_is_short_enough_for_the_screen_to_repeat_it(client_local, org):
    resp = client_local.post(f"/{org.slug}/capture", {"title": "anything"})
    assert resp.status_code == 402
    body = resp.content.decode()
    assert body == REASON
    assert len(body) < _toast_ceiling(), (
        "the client falls back to a generic message above this length, so the "
        "explanation the server wrote never reaches the person who needs it"
    )


@BLOCK
@pytest.mark.django_db
def test_the_refusal_is_plain_text_rather_than_an_error_page(client_local, org):
    """The client refuses anything starting with '<' — an HTML page is not a
    message — so a well-meant change to a rendered 402 template would silence
    this without failing anything."""
    resp = client_local.post(f"/{org.slug}/capture", {"title": "anything"})
    assert resp["Content-Type"].startswith("text/plain")
    assert not resp.content.decode().startswith("<")
