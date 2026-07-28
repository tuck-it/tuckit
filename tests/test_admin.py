"""Smoke tests for the core Django admin registrations.

These guard the local-dev admin: every core model should be registered and its
changelist should render for a superuser. Catches registration mistakes (e.g. a
list_display field that doesn't exist, or a broken custom User admin).
"""

import pytest
from django.contrib import admin
from django.urls import reverse

from tuckit.core.models import (
    ActivityEvent,
    ApiToken,
    Area,
    Bite,
    Invitation,
    Org,
    OrgMember,
    OrgStatSnapshot,
    Slice,
    Tag,
    User,
)

CORE_MODELS = [
    User,
    Org,
    OrgMember,
    Invitation,
    ApiToken,
    OrgStatSnapshot,
    Tag,
    Area,
    Slice,
    Bite,
    ActivityEvent,
]


@pytest.fixture
def admin_client(client, db):
    superuser = User.objects.create_superuser(email="admin@tuckit.local", password="pw")
    client.force_login(superuser)
    return client


@pytest.mark.parametrize("model", CORE_MODELS, ids=lambda m: m.__name__)
def test_core_model_registered(model):
    assert model in admin.site._registry, f"{model.__name__} is not registered in the admin"


@pytest.mark.parametrize("model", CORE_MODELS, ids=lambda m: m.__name__)
def test_admin_changelist_renders(admin_client, model):
    url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
    resp = admin_client.get(url)
    assert resp.status_code == 200


def test_admin_index_renders(admin_client):
    resp = admin_client.get(reverse("admin:index"))
    assert resp.status_code == 200


# --- No staff-reachable path that destroys a slice's steps ------------------


@pytest.mark.django_db
def test_slice_admin_has_no_plan_inline(admin_client):
    """Bite.plan is still on_delete=CASCADE this release (0045 leaves it
    populated for every pre-release bite; the column drop is 0047), so a Plan
    inline on SliceAdmin was a live, staff-reachable checkbox that destroyed a
    slice's steps with no undo — in a release whose claim is that nothing is
    irreversible. Nothing creates Plans any more, so the inline had no reason
    to exist either."""
    from tuckit.core.models import Plan
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite

    slice_admin = admin.site._registry[Slice]
    assert list(slice_admin.inlines) == []
    assert not any(getattr(i, "model", None) is Plan for i in slice_admin.inlines)

    # ...and the change form itself offers no plan-delete checkbox.
    org = Org.objects.create(name="Admin Org", slug="admin-org", key="AO")
    s = create_slice(org, area=create_area(org, "A"), title="Has steps")
    create_bite(s, "step one")
    url = reverse("admin:core_slice_change", args=[s.id])
    body = admin_client.get(url).content.decode()
    assert "plans-" not in body        # inline formset prefix
    assert "plans-0-DELETE" not in body
    assert s.bites.count() == 1


@pytest.mark.django_db
def test_bite_admin_does_not_display_plan():
    """`plan` is a column on its way out (0047). Showing it in the changelist
    keeps a dead layer visible and sortable long after nothing writes it."""
    bite_admin = admin.site._registry[Bite]
    assert "plan" not in bite_admin.list_display
    assert "slice" in bite_admin.list_display
