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


def test_heat_decays_from_the_seeded_timestamp():
    """Static assertion on purpose: a decay that silently never runs still
    renders a valid page and returns 200, so no endpoint test can see it."""
    js = (Path(tuckit.web.__file__).parent / "static/web/heat.js").read_text()
    js = " ".join(js.split())
    assert "data-last-touch" in js
    assert "--heat" in js


def test_the_old_ring_is_gone():
    """The ring and the warmth would be two languages for one idea."""
    css = (Path(tuckit.web.__file__).parent / "static/web/app.css").read_text()
    assert "just-live" not in css
    live_js = (Path(tuckit.web.__file__).parent / "static/web/live.js").read_text()
    assert "just-live" not in live_js
