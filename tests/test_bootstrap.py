import pytest

from tuckit.core.management.commands.bootstrap import ensure_bootstrap
from tuckit.core.models import Area, OrgMember, User, Workspace


@pytest.mark.django_db
def test_bootstrap_creates_full_local_setup():
    workspace, raw = ensure_bootstrap()
    assert Workspace.objects.count() == 1
    assert User.objects.filter(username="local").exists()
    assert OrgMember.objects.filter(org=workspace.org, role="owner").exists()
    assert Area.objects.filter(workspace=workspace, slug="default").exists()
    assert Area.objects.filter(workspace=workspace, is_inbox=True).count() == 1
    assert raw is not None  # token minted on first run


@pytest.mark.django_db
def test_bootstrap_is_idempotent():
    ensure_bootstrap()
    workspace, raw = ensure_bootstrap()
    assert Workspace.objects.count() == 1
    assert OrgMember.objects.count() == 1
    assert Area.objects.filter(workspace=workspace).count() == 2
    assert raw is None  # no new token on subsequent runs


@pytest.mark.django_db
def test_bootstrap_creates_inbox_area():
    from tuckit.core.services.areas import get_or_create_inbox
    ws, _ = ensure_bootstrap()
    assert ws.areas.filter(is_inbox=True).count() == 1
