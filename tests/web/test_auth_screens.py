import pytest
from django.test import override_settings

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.invitations import create_invitation


@pytest.mark.django_db
def test_login_screen_uses_design_system(client):
    body = client.get("/login/").content.decode()
    # standalone page, English, not the app shell
    assert '<html lang="en"' in body
    # token chain linked in order, ending in auth.css; app.css NOT linked
    i_brand = body.find("tokens.brand.css")
    i_product = body.find("tokens.product.css")
    i_base = body.find("web/base.css")
    i_auth = body.find("web/auth.css")
    assert -1 not in (i_brand, i_product, i_base, i_auth)
    assert i_brand < i_product < i_base < i_auth
    assert "web/app.css" not in body
    # email-first entry: split panel + email field, no password on this step
    assert 'class="auth-split"' in body
    assert 'name="email"' in body
    assert 'type="password"' not in body


@pytest.mark.django_db
def test_login_has_brand_panel_with_tagline(client):
    body = client.get("/login/").content.decode()
    assert "auth-panel" in body
    assert "Your project shouldn't." in body


@pytest.mark.django_db
def test_invite_screen_uses_design_system(client):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="o@a.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    inv = create_invitation(org=org, email="new@x.com", role="member", invited_by=owner)
    body = client.get(f"/invite/{inv.token}/").content.decode()
    assert 'class="auth-card"' in body
    assert "web/auth.css" in body
    assert "web/app.css" not in body
    assert "Join Acme" in body          # English heading with org name
    assert "new@x.com" in body          # locked email shown for anonymous invitee
    assert 'name="password"' in body


@pytest.mark.django_db
@override_settings(TUCKIT_MARKETING_URL="https://tuckit.dev")
def test_auth_brand_links_to_marketing_when_set(client):
    body = client.get("/login/").content.decode()
    assert '<a class="auth-panel-brand" href="https://tuckit.dev">' in body


@pytest.mark.django_db
@override_settings(TUCKIT_MARKETING_URL="")
def test_auth_brand_plain_when_unset(client):
    body = client.get("/login/").content.decode()
    assert '<a class="auth-panel-brand"' not in body
    assert '<div class="auth-panel-brand">' in body
