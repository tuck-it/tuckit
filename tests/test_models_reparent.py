import pytest

from tuckit.core.models import ApiToken, Area, Org, Tag, Workspace


@pytest.fixture
def org(db):
    return Org.objects.create(name="Acme", slug="acme")


@pytest.fixture
def ws(org):
    # workspace is still a required (non-null) FK on these models until the
    # final strangler-fig task, so every creation site here needs both.
    return Workspace.objects.create(org=org, name="Acme WS", slug="acme-ws")


@pytest.mark.django_db
def test_area_belongs_to_org(org, ws):
    area = Area.objects.create(workspace=ws, org=org, name="Backend", slug="backend", rank="n")
    assert area.org == org
    assert list(org.areas.all()) == [area]


@pytest.mark.django_db
def test_tag_belongs_to_org(org, ws):
    tag = Tag.objects.create(workspace=ws, org=org, name="urgent")
    assert list(org.tags.all()) == [tag]


@pytest.mark.django_db
def test_api_token_belongs_to_org(org, ws):
    token = ApiToken.objects.create(workspace=ws, org=org, name="agent", token_hash="x" * 64)
    assert list(org.tokens.all()) == [token]
