import json

import pytest

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.fixture
def ctx(client, db):
    org = Org.objects.create(name="Acme", slug="acme")
    owner = User.objects.create(email="o@acme.com")
    OrgMember.objects.create(user=owner, org=org, role="owner")
    create_slice(org, area=create_area(org, "Backend"), title="A slice")
    client.force_login(owner)
    return client, org


def _url(org, view, fmt):
    return f"/{org.slug}/settings/export/download?view={view}&format={fmt}"


@pytest.mark.django_db
@pytest.mark.parametrize("view,fmt,ext", [
    ("full", "json", ".json"), ("full", "md", ".zip"), ("report", "csv", ".csv"),
])
def test_each_combination_downloads_as_an_attachment(ctx, view, fmt, ext):
    client, org = ctx
    resp = client.get(_url(org, view, fmt))
    assert resp.status_code == 200
    disposition = resp["Content-Disposition"]
    assert disposition.startswith("attachment;")
    assert ext in disposition
    assert resp.content


@pytest.mark.django_db
def test_the_json_download_is_parseable(ctx):
    client, org = ctx
    payload = json.loads(client.get(_url(org, "full", "json")).content)
    assert payload["tuckit_export"]["org"]["slug"] == "acme"


@pytest.mark.django_db
def test_the_csv_download_keeps_its_bom(ctx):
    client, org = ctx
    assert client.get(_url(org, "report", "csv")).content.startswith(b"\xef\xbb\xbf")


@pytest.mark.django_db
def test_a_blocked_combination_is_400_with_an_explanation(ctx):
    client, org = ctx
    resp = client.get(_url(org, "full", "csv"))
    assert resp.status_code == 400
    assert b"full" in resp.content and b"csv" in resp.content


@pytest.mark.django_db
@pytest.mark.parametrize("query", [
    "?view=nonsense&format=json", "?view=full&format=xlsx", "",
])
def test_unknown_parameters_are_400_not_a_surprise_file(ctx, query):
    client, org = ctx
    resp = client.get(f"/{org.slug}/settings/export/download{query}")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_a_non_member_gets_404_because_the_org_is_not_disclosed(client, db):
    """TenantMiddleware hides the org's existence; it is 404, never 403."""
    org = Org.objects.create(name="Acme", slug="acme")
    stranger = User.objects.create(email="s@s.com")
    other = Org.objects.create(name="Other", slug="other")
    OrgMember.objects.create(user=stranger, org=other, role="owner")
    client.force_login(stranger)
    assert client.get(_url(org, "full", "json")).status_code == 404


@pytest.mark.django_db
def test_a_plain_member_can_export_today(client, db):
    """Today's `member` is an editor — there is no read-only seat (TP-148)."""
    org = Org.objects.create(name="Acme", slug="acme")
    member = User.objects.create(email="m@acme.com")
    OrgMember.objects.create(user=member, org=org, role="member")
    client.force_login(member)
    assert client.get(_url(org, "full", "json")).status_code == 200


@pytest.mark.django_db
def test_the_gate_is_wired_even_though_no_role_fails_it_today(ctx, monkeypatch):
    """Guards the seam TP-148 will tighten: prove the 403 branch is reachable."""
    client, org = ctx
    monkeypatch.setattr("tuckit.web.views.export.can_export_org",
                        lambda user, org: False)
    assert client.get(_url(org, "full", "json")).status_code == 403


@pytest.mark.django_db
def test_an_empty_org_downloads_rather_than_500(client, db):
    org = Org.objects.create(name="Empty", slug="empty")
    user = User.objects.create(email="e@e.com")
    OrgMember.objects.create(user=user, org=org, role="owner")
    client.force_login(user)
    for view, fmt in [("full", "json"), ("full", "md"), ("report", "csv")]:
        assert client.get(_url(org, view, fmt)).status_code == 200
