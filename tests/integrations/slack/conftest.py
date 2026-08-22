"""Fixtures shared by the Slack integration suite.

`client_local` intentionally reuses the name `tests/web/conftest.py` gives its
logged-in client, because it means the same thing. That one is bootstrap-based
and scoped to tests/web/; this one is bound to the `member` fixture below.
"""
import itertools

import pytest

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.slices import create_slice

_counter = itertools.count(1)


@pytest.fixture
def user_factory(db):
    def make(email: str | None = None) -> User:
        n = next(_counter)
        return User.objects.create_user(email=email or f"person{n}@example.com", password="x")
    return make


@pytest.fixture
def org_factory(db):
    def make(name: str | None = None) -> Org:
        n = next(_counter)
        return Org.objects.create(name=name or f"Org {n}", slug=f"org-{n}")
    return make


@pytest.fixture
def member_factory(org, user_factory):
    def make(org_=None, role: str = "owner") -> OrgMember:
        return OrgMember.objects.create(user=user_factory(), org=org_ or org, role=role)
    return make


@pytest.fixture
def member(member_factory) -> OrgMember:
    """An ACTIVE membership in `org`. ended_at is None."""
    return member_factory()


@pytest.fixture
def slice_factory(org):
    def make(org_=None, title: str = "A slice", **kwargs):
        return create_slice(org_ or org, title=title, **kwargs)
    return make


@pytest.fixture
def other_org(org_factory) -> Org:
    return org_factory("Other Org")


@pytest.fixture
def other_org_member(other_org, member_factory) -> OrgMember:
    return member_factory(other_org)


@pytest.fixture
def other_org_slice(other_org, slice_factory):
    return slice_factory(other_org, title="Belongs elsewhere")


@pytest.fixture
def client_local(client, member):
    client.force_login(member.user)
    return client


class FakeSlack:
    """Stands in for SlackClient. Records rather than calls.

    Shared by every handler test so the two suites cannot drift apart.
    """

    def __init__(self, *args, **kwargs):
        self.posted, self.updated, self.ephemeral, self.unfurled = [], [], [], []
        self.replies = [
            {"user": "U1", "text": "the bug"},
            {"user": "U2", "text": "<@U0> file it"},
        ]

    def post_message(self, **kwargs):
        self.posted.append(kwargs)
        return "ts-1"

    def update_message(self, **kwargs):
        self.updated.append(kwargs)

    def post_ephemeral(self, **kwargs):
        self.ephemeral.append(kwargs)

    def conversations_replies(self, **kwargs):
        return self.replies

    def chat_unfurl(self, **kwargs):
        self.unfurled.append(kwargs)


@pytest.fixture
def fake_slack(monkeypatch):
    holder = FakeSlack()
    monkeypatch.setattr(
        "tuckit.integrations.slack.handlers.SlackClient", lambda *a, **k: holder,
    )
    return holder
