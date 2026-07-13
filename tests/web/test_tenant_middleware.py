import pytest
from django.http import Http404
from django.test import RequestFactory

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.orgs import create_workspace
from tuckit.web.middleware import TenantMiddleware


def _view(request, *args, **kwargs):
    return None


@pytest.fixture
def tenant(db):
    member = User.objects.create(email="member@a.com")
    outsider = User.objects.create(email="outsider@a.com")
    org = Org.objects.create(name="Acme", slug="acme")
    OrgMember.objects.create(user=member, org=org, role="owner")
    ws = create_workspace(org, "Design")
    return member, outsider, org, ws


@pytest.mark.django_db
def test_member_resolves_and_strips_kwargs(tenant):
    member, _outsider, org, ws = tenant
    request = RequestFactory().get(f"/{org.slug}/{ws.slug}/")
    request.user = member
    request.session = {}
    view_kwargs = {"org_slug": org.slug, "ws_slug": ws.slug, "keep": "me"}

    mw = TenantMiddleware(lambda r: r)
    result = mw.process_view(request, _view, [], view_kwargs)

    assert result is None
    assert request.org == org
    assert request.workspace == ws
    # slug kwargs stripped so content views keep their signatures
    assert "org_slug" not in view_kwargs
    assert "ws_slug" not in view_kwargs
    assert view_kwargs == {"keep": "me"}
    # active workspace persisted for root_redirect / switcher
    assert request.session["active_workspace_id"] == ws.id


@pytest.mark.django_db
def test_nonmember_raises_404(tenant):
    _member, outsider, org, ws = tenant
    request = RequestFactory().get(f"/{org.slug}/{ws.slug}/")
    request.user = outsider
    request.session = {}
    view_kwargs = {"org_slug": org.slug, "ws_slug": ws.slug}

    mw = TenantMiddleware(lambda r: r)
    with pytest.raises(Http404):
        mw.process_view(request, _view, [], view_kwargs)
