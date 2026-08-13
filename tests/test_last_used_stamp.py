from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from tuckit.core.models import ApiToken, Org, OrgMember
from tuckit.core.services import oauth
from tuckit.core.services.tokens import STAMP_INTERVAL, generate_token, resolve_org


@pytest.fixture
def org(db):
    return Org.objects.create(name="Acme", slug="acme")


def test_the_first_resolution_stamps_last_used_at(org):
    token, raw = generate_token(org, "t")
    assert token.last_used_at is None
    resolve_org(raw)
    token.refresh_from_db()
    assert token.last_used_at is not None


def test_a_second_resolution_inside_the_window_does_not_write(org, django_assert_num_queries):
    token, raw = generate_token(org, "t")
    resolve_org(raw)
    # One SELECT and no UPDATE. This is the whole point: a refused request must
    # not cost a database write.
    with django_assert_num_queries(1):
        resolve_org(raw)


def test_a_resolution_past_the_window_writes_again(org):
    token, raw = generate_token(org, "t")
    resolve_org(raw)
    token.refresh_from_db()
    stale = timezone.now() - STAMP_INTERVAL - timedelta(seconds=1)
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=stale)
    resolve_org(raw)
    token.refresh_from_db()
    assert token.last_used_at > stale


def test_the_oauth_path_is_throttled_too(org, django_assert_num_queries):
    user = get_user_model().objects.create_user(email="a@b.co", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    client = oauth.create_client("Claude Code", ["http://localhost/cb"])
    access, _refresh, _ttl = oauth.issue_tokens(client, user, org, "mcp")
    oauth.resolve_oauth_org(access)
    with django_assert_num_queries(1):
        oauth.resolve_oauth_org(access)
