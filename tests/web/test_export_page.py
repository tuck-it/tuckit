import pytest

from tuckit.core.models import Org, OrgMember, User


@pytest.fixture
def ctx(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="o@acme.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    client.force_login(owner)
    return client, org


@pytest.mark.django_db
def test_page_renders_in_the_settings_shell(ctx):
    client, org = ctx
    resp = client.get(f"/{org.slug}/settings/export")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'class="settings-nav"' in body
    assert 'class="sidebar"' not in body


@pytest.mark.django_db
def test_page_offers_all_three_downloads(ctx):
    client, org = ctx
    body = client.get(f"/{org.slug}/settings/export").content.decode()
    for view, fmt in [("full", "json"), ("full", "md"), ("report", "csv")]:
        assert f"view={view}&amp;format={fmt}" in body, f"{view}/{fmt} missing"


@pytest.mark.django_db
def test_page_says_json_is_the_lossless_one(ctx):
    """Excel shortens long cells; the page has to say where the full text is."""
    client, org = ctx
    body = client.get(f"/{org.slug}/settings/export").content.decode()
    assert "32,767" in body
    assert "JSON" in body


@pytest.mark.django_db
def test_nav_shows_export_and_marks_it_active(ctx):
    client, org = ctx
    body = client.get(f"/{org.slug}/settings/export").content.decode()
    assert f'href="/{org.slug}/settings/export"' in body
    assert 'class="settings-item on"' in body


@pytest.mark.django_db
def test_nav_shows_export_on_other_settings_pages_too(ctx):
    client, org = ctx
    body = client.get(f"/{org.slug}/settings/general").content.decode()
    assert f'href="/{org.slug}/settings/export"' in body


@pytest.mark.django_db
def test_a_plain_member_sees_the_page_and_the_nav_item(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    member = User.objects.create(email="m@acme.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    client.force_login(member)
    resp = client.get(f"/{org.slug}/settings/export")
    assert resp.status_code == 200
    assert f'href="/{org.slug}/settings/export"' in resp.content.decode()


@pytest.mark.django_db
def test_a_non_member_gets_404(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    other = Org.objects.create(name="Other", slug="other")
    stranger = User.objects.create(email="s@s.com")
    OrgMember.objects.create(user=stranger, org=other, role="owner")
    client.force_login(stranger)
    assert client.get(f"/{org.slug}/settings/export").status_code == 404
