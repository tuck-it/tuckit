import pytest

from tuckit.core.management.commands.bootstrap import ensure_bootstrap
from tuckit.core.models import User


@pytest.fixture
def org(db):
    org, _ = ensure_bootstrap()
    return org


@pytest.fixture
def client_local(client, org):
    user = User.objects.get(email="local@tuckit.local")
    client.force_login(user)
    return client
