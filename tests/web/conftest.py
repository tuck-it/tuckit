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


def bite_under_plan(plan_, slice_, title, **kw):
    """The slice detail modal still groups bites by Plan (Task 10 retires
    this). create_bite() no longer sets bite.plan (Task 5), so a bite that
    must render inside a specific plan section has to be reparented onto it
    explicitly after creation."""
    from tuckit.core.services.bites import create_bite

    b = create_bite(slice_, title, **kw)
    b.plan = plan_
    b.save(update_fields=["plan"])
    return b
