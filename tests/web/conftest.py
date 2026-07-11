import pytest

from tuckit.core.management.commands.bootstrap import ensure_bootstrap
from tuckit.core.models import User


@pytest.fixture
def workspace(db):
    ws, _ = ensure_bootstrap()
    return ws


@pytest.fixture
def client_local(client, workspace):
    user = User.objects.get(username="local")
    client.force_login(user)
    return client
