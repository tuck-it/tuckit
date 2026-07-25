from pathlib import Path

import pytest
from django.urls import reverse
from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area

import tuckit.web


def _live_js():
    return (Path(tuckit.web.__file__).parent / "static/web/live.js").read_text()


@pytest.fixture
def member(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create_user(email="m@b.co", password="pw123456")
    OrgMember.objects.create(user=user, org=org, role="owner")
    return org, user


@pytest.mark.django_db
def test_live_config_present_on_tenant_page(client, member):
    org, user = member
    create_area(org, "Backend")
    client.force_login(user)
    html = client.get(reverse("web:inbox", args=[org.slug])).content.decode()
    assert 'id="live-config"' in html
    assert f"/{org.slug}/live" in html
    assert 'data-cursor="' in html


@pytest.mark.django_db
def test_inbox_marks_main_live(client, member):
    org, user = member
    client.force_login(user)
    html = client.get(reverse("web:inbox", args=[org.slug])).content.decode()
    assert 'data-live-refresh="1"' in html


def test_highlight_selector_prefers_the_events_highlight_target():
    """Static assertion on purpose: the failure this pins (a highlight silently
    matching nothing) renders fine and returns 200, so no endpoint test can see
    it. Building the selector from target_type is what left every bite event
    unhighlighted — the event now names its own highlight target."""
    handler = _live_js().split('"tuckit:live-refreshed"', 1)[1]
    handler = " ".join(handler.split())          # formatting-agnostic
    # The event's highlight target wins; non-bite events ship no highlight_* keys,
    # so the fallback to the target itself has to stay.
    assert "ev.highlight_type || ev.target_type" in handler
    assert "ev.highlight_id || ev.target_id" in handler
