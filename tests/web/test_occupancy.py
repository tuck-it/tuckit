"""Occupancy is seeded server-side because a screen can load with items ALREADY
warm — without a seed they would render cold until the next event arrived."""

from pathlib import Path

import pytest
from django.urls import reverse

import tuckit.web
from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.plans import create_plan
from tuckit.core.services.slices import create_slice


@pytest.fixture
def member(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user(email="m@b.co", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    return org, user


@pytest.mark.django_db
def test_recent_agent_work_seeds_the_slice_row(client, member):
    org, user = member
    slice_ = create_slice(create_area(org, "Backend"), "Login", status="open")
    create_bite(slice_, "Wire the form", source="agent")
    client.force_login(user)

    html = client.get(reverse("web:home", args=[org.slug])).content.decode()

    assert "data-last-touch=" in html
    assert "Wire the form" in html


@pytest.mark.django_db
def test_agent_mark_is_aria_hidden(client, member):
    """Server occupancy holds for 300s but the client fade (heat.js) ends at
    120s, so the mark can sit fully transparent for up to 3 minutes while its
    row is still a live link. Without aria-hidden a screen reader would keep
    announcing it long after it stopped being visible — the toast already
    announced the same event once, which is the right number of times."""
    org, user = member
    slice_ = create_slice(create_area(org, "Backend"), "Login", status="open")
    create_bite(slice_, "Wire the form", source="agent")
    client.force_login(user)

    html = client.get(reverse("web:home", args=[org.slug])).content.decode()

    assert '<span class="agent-mark" aria-hidden="true">' in html


@pytest.mark.django_db
def test_a_cold_slice_carries_no_occupancy_markup(client, member):
    """No attribute at all when cold — the client keys off its presence."""
    org, user = member
    create_slice(create_area(org, "Backend"), "Login", status="open")  # human-created
    client.force_login(user)

    html = client.get(reverse("web:home", args=[org.slug])).content.decode()

    assert "data-last-touch=" not in html
    assert "agent-mark" not in html


def test_the_progress_bar_transitions_its_width():
    """The bar is the main number that moves while an agent works; before morph
    it could not animate at all, so this is the payoff for that change."""
    css = (Path(tuckit.web.__file__).parent / "static/web/app.css").read_text()
    block = css.split(".row-prog-track i {", 1)[1].split("}", 1)[0]
    assert "transition" in block
    assert "width" in block


def test_all_live_motion_is_suppressed_under_reduced_motion():
    """Occupancy must still be READABLE without motion — the label carries the
    same information in words, so only the movement is dropped, not the state."""
    css = (Path(tuckit.web.__file__).parent / "static/web/app.css").read_text()
    blocks = css.split("@media (prefers-reduced-motion: reduce)")
    assert len(blocks) > 1
    guarded = " ".join(blocks[1:])
    for name in ("item-enter", "item-exit", ".row-prog-track i"):
        assert name in guarded, f"{name} keeps animating under reduced motion"
